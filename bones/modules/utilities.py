# -*- encoding: utf8 -*-
import json
import re
import urllib

import bones.event
from bones.bot import Module


class NickFix(Module):
    def __init__(self, *args, **kwargs):
        Module.__init__(self, *args, **kwargs)
        self.nickIWant = None
        self.isRecovering = False

    @bones.event.handler(event=bones.event.UserQuitEvent)
    @bones.event.handler(event=bones.event.UserNickChangedEvent)
    def somethingHappened(self, myEvent):
        user = None
        if self.nickIWant is None:
            self.nickIWant = \
                self.settings.get("bot", "nickname").split("\n")[0]

        if isinstance(myEvent, bones.event.UserNickChangedEvent) is True:
            user = myEvent.oldname
        else:
            user = myEvent.user.nickname

        if user.lower() == self.nickIWant.lower():
            myEvent.client.factory.nicknames = \
                self.settings.get("bot", "nickname").split("\n")[1:]
            self.isRecovering = True
            myEvent.client.setNick(self.nickIWant)

    @bones.event.handler(event=bones.event.BotSignedOnEvent)
    def resetMe(self, event):
        self.isRecovering = False
        self.nickIWant = None

    @bones.event.handler(event=bones.event.PreNicknameInUseError)
    def shouldWeEvenTry(self, event):
        if self.isRecovering:
            event.isCancelled = True
            self.isRecovering = False


class Ping(Module):
    def __init__(self, *args, **kwargs):
        Module.__init__(self, *args, **kwargs)
        self.ongoingPings = {}

    @bones.event.handler(trigger="ping")
    def cmdPing(self, event):
        nick = event.user.nickname
        if nick not in self.ongoingPings:
            self.ongoingPings[nick] = event.channel.name
            event.user.ping()
        else:
            event.user.notice(
                "Please wait until your ongoing ping in %s is finished until "
                "trying again."
                % self.ongoingPings[nick]
            )

    @bones.event.handler(event=bones.event.CTCPPongEvent)
    def eventPingResponseReceive(self, event):
        nick = event.user.nickname
        if nick in self.ongoingPings:
            event.user.notice("%s: Your response time was %.3f seconds."
                              % (nick, event.secs))
            del self.ongoingPings[nick]


class Twitter(Module):
    bs = None
    urlopener = None

    reTweetLink = re.compile("(https?\:\/\/)?twitter\.com\/[a-zA-Z0-9\-\_]+\/status\/\d+", re.IGNORECASE)  # NOQA

    def __init__(self, *args, **kwargs):
        Module.__init__(self, *args, **kwargs)
        try:
            from bs4 import BeautifulSoup
            self.bs = BeautifulSoup
        except ImportError:
            self.log.warn(
                "Unmet dependency BeautifulSoup4: The URL checkers will be "
                "disabled."
            )

    @bones.event.handler(event=bones.event.ChannelMessageEvent)
    def eventURLInfo_Twitter(self, event):
        if self.bs is None:
            return

        if "twitter" in event.message and "http" in event.message:
            data = self.reTweetLink.search(event.message)

            if not data:
                return

            url = data.group(0)
            html = event.client.factory.urlopener.open(url).read()
            soup = self.bs(html)
            tweet = soup \
                .find("div",
                      {"class": "permalink-inner permalink-tweet-container"}) \
                .find("p", {"class": "tweet-text"}) \
                .text
            tweet = u"↵ ".join(tweet.split("\n"))
            user = soup \
                .find("div",
                      {"class": "permalink-inner permalink-tweet-container"}) \
                .find("span", {"class": "username js-action-profile-name"}) \
                .text

            # shitty fix for pic.twitter.com links
            # could be improved by going through all links, check
            # whether they start with http and if not replace the
            # nodeText with the href attribute.
            out = []
            for word in tweet.split(" "):
                if word.startswith("pic.twitter.com"):
                    word = "https://%s" % word
                out.append(word)
            tweet = " ".join(out)

            msg = (u"\x0310Twitter\x03 \x0311::\x03 %s \x0311––\x03 %s"
                   % (tweet, user))
            event.channel.msg(msg.encode("utf-8"))


class YouTube(Module):
    bs = None

    reVideoLink = re.compile("(https?\:\/\/)?(m\.|www\.)?(youtube\.com\/watch\?(.+)?v\=|youtu\.be\/)(?P<id>[a-zA-Z-0-9\_\-]*)")  # NOQA
    __template_simple = u"\x0314You\x035Tube \x0314::\x03 {title} \x034::\x03 http://youtu.be/{id}"  # NOQA
    __template_api = u"\x0314You\x035Tube \x034::\x03 {title}\x0314, {snippet[channelTitle]} \x034::\x0314 {duration} {definition} \x034::\x03 http://youtu.be/{id}"  # NOQA

    apiEndpoint = "https://www.googleapis.com/youtube/v3/%s?%s"

    def __fetchData(x):
        return {
            "template": "html", "title": "Something went wrong"
        }

    def __init__(self, *args, **kwargs):
        Module.__init__(self, *args, **kwargs)
        self.fetchData = self.__fetchData

        self.template_simple = self.settings.get(
            "module.utilities",
            "youtube.template.simple",
            default=self.__template_simple
        )
        self.template_api = self.settings.get("module.utilities",
                                              "youtube.template.api",
                                              default=self.__template_api)
        self.apikey = self.settings.get("module.utilities", "youtube.apikey",
                                        default=None)
        if not self.apikey:
            self.log.warn(
                "No API key provided. Video search and detailed video info "
                "will be disabled.")
            self.fetchData = self.fetchData_Html
        else:
            self.fetchData = self.fetchData_YouTubeApi

        if not self.apikey:
            try:
                from bs4 import BeautifulSoup
                self.bs = BeautifulSoup
            except ImportError:
                self.log.warn(
                    "Unmet dependency BeautifulSoup4: The URL checkers will "
                    "be disabled."
                )

    def api_request(self, method, **args):
        args["key"] = self.apikey
        url = self.apiEndpoint % (method, urllib.urlencode(args))
        result = self.factory.urlopener.open(url).read()
        return json.loads(result)

    def fetchData_Html(self, video):
        url = "http://youtube.com/watch?%s" % urllib.urlencode({"v": video})
        html = self.factory.urlopener.open(url).read()
        soup = self.bs(html)
        title = soup.find("span", {"id": "eow-title"}).text.strip()
        return {
            "template": "html",
            "id": video,
            "title": title,
        }

    def api_videoDetails(self, video):
        return self.api_request("videos",
                                part="statistics,snippet,contentDetails",
                                id=video)

    def api_videoSearch(self, term):
        data = self.api_request("search", part="id", safeSearch="none",
                                order="relevance", type="video",
                                maxResults="1", q=term)
        if not data or "items" not in data or len(data["items"]) < 1:
            return None
        return self.fetchData_YouTubeApi(data["items"][0]["id"]["videoId"])

    def fetchData_YouTubeApi(self, video):
        data = self.api_videoDetails(video)
        if not data["items"]:
            return
        output = data["items"][0]
        output.update(output["snippet"])
        output["duration"] = output["contentDetails"]["duration"].lower()[2:]
        output["definition"] = output["contentDetails"]["definition"].upper()
        output["template"] = "api"
        return output

    def sendToChannel(self, channel, data):
        if data["template"] == "api":
            output = self.template_api
        else:
            output = self.template_simple

        output = output.format(**data)
        output = u"↵ ".join(output.split("\n"))
        channel.msg(output.encode("utf-8"))

    @bones.event.handler(event=bones.event.ChannelMessageEvent)
    def checkMessageForUrl(self, event):
        if not self.bs and not self.apikey:
            return
        if not ("youtu" in event.message and "http" in event.message):
            return

        data = self.reVideoLink.search(event.message)
        if not data:
            return

        video_data = self.fetchData(data.group("id"))
        if not video_data:
            return
        self.sendToChannel(event.channel, video_data)

    @bones.event.handler(trigger="yt")
    @bones.event.handler(trigger="youtube")
    def videoSearch(self, event):
        if not self.apikey:
            return
        term = " ".join(event.args)
        video = self.api_videoSearch(term)
        if not video:
            event.reply("No such results.")
        self.sendToChannel(event.channel, video)
