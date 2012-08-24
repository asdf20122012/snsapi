# -*- coding: utf-8 -*-

'''
snsapi base class. 

All plugins are derived from this class. 
It provides common authenticate and communicate methods.
'''
import webbrowser
try:
    import json
except ImportError:
    import simplejson as json
import time
import urllib
import oauth
from utils import JsonObject
import errors
import base64
import urlparse
import datetime
import snstype
import subprocess
import utils

from snslog import SNSLog
logger = SNSLog

class SNSAPI(object):
    def __init__(self):
        self.app_key = None
        self.app_secret = None
        self.domain = None
        self.token = None
        self.channel_name = None

        self.auth_info = snstype.AuthenticationInfo()
        self.__fetch_code_timeout = 2
        self.__fetch_code_max_try = 30

        self.console_input = lambda : utils.console_input()

    def fetch_code(self):
        if self.auth_info.cmd_fetch_code == "(built-in)" :
            url = self.__fetch_code()
            return url
        else :
            #url = self.fetch_code() 
            cmd = "%s %s" % (self.auth_info.cmd_fetch_code, self.__last_request_time)
            logger.debug("fetch_code command is: %s", cmd) 
            ret = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True).stdout.readline().rstrip()
            tries = 1 
            while ret == "(null)" :
                tries += 1
                if tries > self.__fetch_code_max_try :
                    break
                time.sleep(self.__fetch_code_timeout)
                ret = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True).stdout.read().rstrip()
            return ret

    def request_url(self, url):
        if self.auth_info.cmd_request_url == "(built-in)" :
            self.__request_url(url)
        else :
            self.__last_request_time = time.time()
            cmd = "%s '%s'" % (self.auth_info.cmd_request_url, url)
            logger.debug("request_url command is: %s", cmd) 
            res = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True).stdout.read().rstrip()
            logger.debug("request_url result is: %s", res) 
            return

    #build-in fetch_code function: read from console
    def __fetch_code(self):
        #print "Please input the whole url from Broswer's address bar:";
        utils.console_output("Please input the whole url from Broswer's address bar:")
        return self.console_input()

    #build-in request_url function: open default web browser
    def __request_url(self, url):
        self.openBrower(url)
        #webbrowser.open(url)
        #print url
        return
    
    def oauth2(self, auth_url, callback_url):
        '''Authorizing using synchronized invocation.
        Invoking APIs from oauth.py
        
        web browser will be open, after that, user need to copy the code back to command window.
        save access_token if authorized.
        @param auth_url: the authorizing url for individual SNS provider, must be set.
        @param callback_url: the SNS provider will send something of a code to this page. 
            Users need to collect the code in the browser's address bar to this client.
            callback_url MUST be the same one you set when you apply for an app in openSNS platform.
        '''
        
        logger.info("Try to authenticate '%s' using OAuth2", self.channel_name)

        authClient = oauth.APIClient(self.app_key, self.app_secret, callback_url, auth_url=auth_url)
        url = authClient.get_authorize_url()

        self.request_url(url)
        
        #Wait for input
        url = self.fetch_code()

        if url == "(null)" :
            raise errors.snsAuthFail
        self.token = self.parseCode(url)
        self.token.update(authClient.request_access_token(self.token.code))
        #print "Authorized! access token is " + str(self.token)
        logger.debug("Authorized! access token is " + str(self.token))
        logger.info("Channel '%s' is authorized", self.channel_name)
    
    def openBrower(self, url):
        return webbrowser.open(url)
    
    def parseCode(self, url):
        '''
        parse code from url for code and openID
        @param url: contain code and openID
        @return: JsonObject within code and openid
        '''
        return JsonObject(urlparse.parse_qsl(urlparse.urlparse(url).query))

    def save_token(self):
        '''
        access token can be saved, it stays valid for a couple of days
        if successfully saved, invoke get_saved_token() to get it back
        '''
        token = JsonObject(self.token)
        #TODO: encrypt access token

        #save token to file "token.save"
        #TODO make the file invisible or at least add it to .gitignore
        fname = self.auth_info.save_token_file
        if fname == "(built-in)" :
            fname = self.channel_name+".token.save"
        if fname != "(null)" :
            with open(fname,"w") as fp:
                json.dump(token, fp)
        
        return True
            
    def get_saved_token(self):
        try:
            fname = self.auth_info.save_token_file
            if fname == "(built-in)" :
                fname = self.channel_name+".token.save"
            if fname != "(null)" :
                with open(fname, "r") as fp:
                    token = JsonObject(json.load(fp))
                    #check expire time
                    if self.isExpired(token):
                        #print "Saved Access token is expired, try to get one through sns.auth() :D"
                        logger.debug("Saved Access token is expired, try to get one through sns.auth() :D")
                        return False
                    #TODO: decrypt token
                    self.token = token
            else:
                logger.debug("This channel is configured not to save token to file")
                return False
                    
        except IOError:
            #print "No access token saved, try to get one through sns.auth() :D"
            logger.debug("No access token saved, try to get one through sns.auth() :D")
            return False

        logger.info("Read saved token for '%s' successfully", self.channel_name)
        return True
    
    def isExpired(self, token=None):
        '''
        check if the access token is expired
        '''
        if token == None:
            token = self.token
            
        #print "==="
        #print token.expires_in 
        #print time.time()
        #print "==="

        if token.expires_in < time.time():
            return True
        else:
            return False
    
    def read_channel(self, channel):
        self.channel_name = channel['channel_name']
        self.platform = channel['platform']
        #if channel['auth_info'] :
        if 'auth_info' in channel :
            self.auth_info = snstype.AuthenticationInfo(channel['auth_info'])

    def setup_app(self, app_key, app_secret):
        '''
        If you do not want to use read_config, and want to set app_key on your own, here it is.
        '''
        self.app_key = app_key
        self.app_secret = app_secret

    def _http_get(self, baseurl, params):
        uri = urllib.urlencode(params)
        url = baseurl + "?" + uri
        resp = urllib.urlopen(url)
        json_objs = json.loads(resp.read())
        return json_objs
    
    def _http_post(self, baseurl, params):
        data = urllib.urlencode(params)
        resp = urllib.urlopen(baseurl,data)
        json_objs = json.loads(resp.read())
        return json_objs

    def _unicode_encode(self, str):
        """
        Detect if a string is unicode and encode as utf-8 if necessary
        """
        return isinstance(str, unicode) and str.encode('utf-8') or str
    
    def home_timeline(self, count=20):
        '''Get home timeline
        get statuses of yours and your friends'
        @param count: number of statuses
        '''
        pass
        
