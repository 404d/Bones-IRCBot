# -*- encoding: utf-8 -*-
from datetime import datetime
import json
import urllib

from sqlalchemy import (
    Column,
    Integer,
    Text,
)

import bones.event
from bones.bot import Module
from bones.modules import storage


class Lastfm(Module):

    def __init__(self, *args, **kwargs):
        Module.__init__(self, *args, **kwargs)
        self.apikey = self.settings.get("module.Lastfm", "apikey",
                                        default=None)
        if not self.apikey:
            self.log.error("No API key provided. Last.fm will be disabled.")

    @bones.event.handler(event=storage.DatabaseInitializedEvent)
    def gotDB(self, event):
        self.db = event.module

    @bones.event.handler(trigger="lastfm")
    def trigger(self, event):
        if not self.apikey:
            self.log.error("No API key provided. Last.fm will be disabled.")
            event.channel.msg("[Last.fm] Configuration error; check the logs "
                              "for more info.")
            return

        (nickname, username, action) = self.parseargs(event)

        if not action:
            return self.showTrack(event, nickname, username)

        elif action == "-r":
            return self.registerUser(event, username)

        elif action == "-d":
            return self.deleteUser(event)

    def api(self, method, **args):
        params = {
            "method": method,
            "api_key": self.apikey,
            "format": "json",
        }
        params.update(args)
        querystring = urllib.urlencode(params)

        data = self.factory.urlopener.open(
            "http://ws.audioscrobbler.com/2.0/?%s" % querystring).read()
        data = json.loads(data)
        return data

    def showTrack(self, event, nickname, username):
        session = self.db.new_session()
        user = self.getUser(session, nickname, username)
        if not user:
            event.channel.msg(
                str("%s: No user registered for nick '%s'"
                    % (event.user.nickname, nickname))
            )
            return

        try:
            data = self.api("user.getRecentTracks", user=user.username,
                            extended=1)
        except ValueError:
            event.channel.msg(
                "[Last.fm] Last.fm returned an invalid response. Please "
                "try again later."
            )
            self.log.exception(
                "An error occurred while fetching user.getRecentTracks for"
                "user %s", nickname)
            return
        except Exception:
            event.channel.msg(
                "[Last.fm] An unexpected error occurred. Please tell the "
                "bot manager to file a bug report."
            )
            self.log.exception(
                "An error occurred while fetching user.getRecentTracks for"
                "user %s", nickname)
            return

        if "error" in data:
            self.log.error("API error %i: %s", data["error"],
                           data["message"])
            event.channel.msg(
                "[Last.fm] An error occurred while processing your "
                "request. Please notify the bot manager"
            )
            return

        if "track" not in data["recenttracks"] \
                or len(data['recenttracks']['track']) < 1:
            event.channel.msg(str(
                "%s: No scrobbles found for user '%s'."
                % (event.user.nickname, user.username)
            ))
            return

        return self.sendTrackToChannel(event, user, data)

    def sendTrackToChannel(self, event, user, data):
        track = data['recenttracks']['track'][0]
        artist = track["artist"]["name"]
        tracktitle = track["name"]

        icon = u"♪"
        if "loved" in track and track["loved"] == "1":
            icon = u"\x034♥\x03"
        msg = u"\x02%s\x02 %s %s \x0305–\x03 %s"
        msg %= (user.username, icon, tracktitle, artist)

        if not ("@attr" in track and "nowplaying" in track["@attr"] and
                track["@attr"]["nowplaying"].lower() == "true"):
            timestamp = track["date"]["uts"]
            date = []

            dateThen = datetime.fromtimestamp(float(timestamp))
            dateNow = datetime.now()
            diff = dateNow - dateThen

            if diff.days > 0:
                date.append("%sd" % diff.days)

            hours = (diff.seconds // 3600) % 24
            if hours > 0 or diff.days > 0:
                date.append("%sh" % hours)

            minutes = (diff.seconds // 60) % 60
            if diff.seconds > 0 or hours > 0 or diff.days > 0:
                date.append("%sm" % minutes)

            date.append("%ss" % (diff.seconds % 60))
            msg += u" \x0315⌛ %s ago" % "".join(date)

        event.channel.msg(str(msg.encode("utf-8")))

    def registerUser(self, event, username):
        session = self.db.new_session()
        if not username:
            event.user.notice(str(
                "[Last.fm] You need to provide a Last.fm username."))
            return

        user = self.getUser(session, event.user.nickname, username)
        user.username = username
        session.begin()
        session.add(user)
        session.commit()
        event.user.notice(str(
            "[Last.fm] Registered '%s' to your nick." % username))

    def deleteUser(self, event):
        session = self.db.new_session()
        user = self.getUser(session, event.user.nickname)
        if not user:
            event.user.notice(str(
                "[Last.fm] No user registered for nick '%s'."
                % event.user.nickname
            ))
            return

        session.begin()
        session.delete(user)
        session.commit()
        event.user.notice(str(
            "[Last.fm] Unregistered your nick from '%s'." % user.username))

    def parseargs(self, event):
        argc = len(event.args)
        action = None
        nickname = None
        username = None
        if argc <= 0:
            nickname = event.user.nickname
            username = nickname
        elif event.args[0] in ["-r", "-d"]:
            action = event.args[0]
            if len(event.args) >= 2:
                username = event.args[1]
        else:
            nickname = event.args[0].decode("utf-8")
            username = nickname
        return (nickname, username, action)

    def getUser(self, session, nickname, username=None):
        user = session.query(User).filter(User.nickname == nickname) \
            .first()

        if user or not username:
            return user

        if not username:
            username = nickname
        data = self.api("user.getInfo", user=username)
        if "error" in data:
            return None

        self.log.info("Found account for unknown user '%s', saving.", nickname)
        user = User(nickname)
        user.username = username
        session.begin()
        session.add(user)
        session.commit()
        return user


class User(storage.Base):
    __tablename__ = "bones_lastfm"

    id = Column(Integer, primary_key=True)
    nickname = Column(Text)
    username = Column(Text)

    def __init__(self, nickname):
        self.nickname = nickname
        self.username = ""


if __name__ == "__main__":
    from ConfigParser import SafeConfigParser
    from sqlalchemy import engine_from_config
    import sys
    settings = SafeConfigParser()
    if len(sys.argv) < 2:
        print "Error: You need to provide a config file!"
        sys.exit(1)
    settings.read(sys.argv[1])
    if "storage" not in settings._sections:
        print "Error: Config file does not contain a 'storage' section."
        sys.exit(1)
    elif "sqlalchemy.url" not in settings._sections["storage"]:
        print("Error: Section 'storage' does not contain an 'sqlalchemy.url' "
              "key.")
        sys.exit(1)
    print("Connecting to '%s'..."
          % settings._sections["storage"]["sqlalchemy.url"])
    engine = engine_from_config(settings._sections["storage"], "sqlalchemy.")
    print "Creating table '%s'..." % User.__tablename__
    from bones.modules.storage import Base
    Base.metadata.create_all(engine)
    print "Have a nice day!"
