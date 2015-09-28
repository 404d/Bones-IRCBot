# -*- encoding: utf8 -*-
import re
import random
from datetime import datetime
import urllib2

from twisted.internet import reactor
from sqlalchemy import (
    Column,
    Integer,
    Text,
)

from bones.bot import Module
import bones.event
from bones.modules import storage


class QDB(Module):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        BeautifulSoup = None

    quotesCache = []

    def __init__(self, settings, factory):
        Module.__init__(self, settings, factory)
        if not self.BeautifulSoup:
            ex = Exception(
                "Unmet dependency: BeautifulSoup 4 not installed. This "
                "dependency needs to be installed before you can use the "
                "module %s" %

                (".".join([__name__, "QDB"],))
            )
            self.log.error(ex)
            raise ex
        self.settings = settings
        self.maxLinesPerQuote = int(
            self.settings.get("module.qdb", "maxLinesPerQuote", default=5))

    @bones.event.handler(trigger="qdb")
    def cmdQdb(self, event):
        if len(event.args) == 1 and event.args[0].isdigit() \
                or len(event.args) >= 2 and event.args[0].lower() == "read":
            if event.args[0].isdigit():
                id = int(event.args[0])
            else:
                id = int(event.args[1])
            self.log.debug("Fetching qdb.us/%i", id)
            try:
                data = event.client.factory.urlopener.open("http://qdb.us/%i"
                                                           % id)
            except urllib2.HTTPError, ex:
                if ex.code == 404:
                    event.channel.msg(str("[QDB #%s] Quote not found." % id))
                    return
                self.log.exception(ex)
                self.log.error("Unable to fetch quote #%i because of an "
                               "HTTP error." % id)
                event.channel.msg("Unable to fetch new quotes")
                return
            if data.getcode() == 404:
                event.channel.msg(str("[QDB #%s] Quote not found." % id))
                return
            if data.getcode() == 200:
                html = data.read()
                soup = self.BeautifulSoup(html)
                quote = soup.find("span", {"class": "qt"}).text
                self.sendQuote(event.channel, (id, quote))
                return
            self.log.error(
                "Got unknown HTTP error code %i when fetching qdb.us/%i",
                data.getcode(), id
            )
            event.channel.msg(str(
                "[QDB] An unknown exception occurred. Please notify the bot "
                "master and try again later."
            ))
            return

        if len(event.args) <= 0 or event.args[0].lower() == "random":
            self.cacheIfNeeded(event.client.factory)
            if len(self.quotesCache) < 1:
                event.channel.msg("Unable to fetch new quotes.")
                return
            quote = self.quotesCache.pop()
            self.sendQuote(event.channel, quote)
            return

    def sendQuote(self, channel, quote):
        lines = quote[1].split("\n")
        if len(lines) > self.maxLinesPerQuote:
            channel.msg(str(
                "[QDB #%s] Quote too long, read it at QDB instead: "
                "http://qdb.us/%s"
                % (quote[0], quote[0])
            ))
            return
        for line in lines:
            channel.msg(str((
                "[QDB #%s] %s"
                % (quote[0], line)
            ).encode("utf-8")))

    def cacheIfNeeded(self, factory):
        """
        Ensures that the quote cache is not empty, and will fetch new quotes
        once the cache is empty.
        """
        if not self.quotesCache:
            self.log.debug("Fetching new quotes from qdb.us/random")
            try:
                html = factory.urlopener.open("http://qdb.us/random").read()
            except urllib2.HTTPError:
                self.log.error("Unable to fetch new quotes because of an HTTP "
                               "error.")
                return
            soup = self.BeautifulSoup(html)
            data = soup.findAll("span", {"class": "qt"})
            for item in data:
                id = item["id"].split("qt")[1]
                self.quotesCache.append((id, item.text))
            self.log.debug("Got %i new quotes", len(self.quotesCache))
            random.shuffle(self.quotesCache, random.random)


class Factoid(storage.Base):
    __tablename__ = "bones_factoids"

    id = Column(Integer, primary_key=True)
    submitter = Column(Text)
    topic = Column(Text)
    fact = Column(Text)

    def __init__(self, topic, fact, submitter):
        self.submitter = submitter
        self.topic = topic
        self.fact = fact


class Factoids(Module):
    reLearn = re.compile("(.+) is (.+)")

    @bones.event.handler(event=storage.DatabaseInitializedEvent)
    def gotDB(self, event):
        self.db = event.module

    @bones.event.handler(trigger="learn")
    def cmdLearnFactoid(self, event):
        match = self.reLearn.match(" ".join(event.args))
        if match:
            session = self.db.new_session()
            session.begin()
            topic = match.group(1)
            fact = match.group(2)
            factoid = Factoid(
                topic,
                fact,
                event.user.nickname
            )
            session.add(factoid)
            session.commit()
            session.close()
            event.reply("I understand")

    @bones.event.handler(event=bones.event.IrcPrivmsgEvent)
    def queryFactoid(self, event):
        if event.message.startswith("?"):
            topic = event.message[1:]
            session = self.db.new_session()
            factoids = session.query(Factoid) \
                .filter(Factoid.topic == topic).all()
            if not factoids:
                return
            msg = "%s is" % topic.decode("utf-8")
            i = 0
            if len(factoids) > 1:
                for factoid in factoids:
                    if i > 0:
                        msg = msg + ", or"
                    i += 1
                    msg = msg + " (#%d) %s" % (i, factoid.fact)
            else:
                msg = msg + " %s" % factoids[0].fact
            event.reply(msg.encode("utf-8"))
            session.close()


class UselessResponses(Module):
    def __init__(self, *args, **kwargs):
        Module.__init__(self, *args, **kwargs)

        self.danceCooldown = {}
        self.danceCooldownTime = None

    @bones.event.handler(event=bones.event.ChannelMessageEvent)
    def DANCE(self, event, step=0):
        msg = re.sub("\x02|\x1f|\x1d|\x16|\x0f|\x03\d{0,2}(,\d{0,2})?", "",
                     event.message)
        if "DANCE" in msg:
            if not self.danceCooldownTime:
                self.danceCooldownTime = int(self.settings.get(
                    "module.UselessResponses", "dance.cooldown", "300"))
            if step == 0:
                if event.channel.name in self.danceCooldown:
                    last = self.danceCooldown[event.channel.name]
                    now = datetime.utcnow()
                    delta = now - last
                    if delta.seconds < self.danceCooldownTime:
                        wait = self.danceCooldownTime - delta.seconds
                        event.user.notice("Please wait %s more seconds."
                                          % wait)
                        return
                self.danceCooldown[event.channel.name] = datetime.utcnow()
                event.client.ctcpMakeQuery(event.channel.name,
                                           [('ACTION', "dances")])
                reactor.callLater(1.5, self.DANCE, event, step=1)
            elif step == 1:
                event.channel.msg(r":D\-<")
                reactor.callLater(1.0, self.DANCE, event, step=2)
            elif step == 2:
                event.channel.msg(r":D|-<")
                reactor.callLater(1.0, self.DANCE, event, step=3)
            elif step == 3:
                event.channel.msg(r":D/-<")

    @bones.event.handler(trigger="hi5")
    def cmdHi5(self, event):
        target = ""
        if len(event.args) > 0:
            target = " ".join(event.args)
        event.channel.msg("(　｀ー´)八(｀ー´　) ＨＩ５ %s" % target)

    @bones.event.handler(trigger="kira")
    def cmdKira(self, event):
        prefix = event.match.group(1)
        if prefix.encode("utf-8") in "★✫✦✧✩✪✫✬✭✮✯✰✴✵✶✷✸✹⭑⭒⭐🌟":
            event.channel.msg("(ﾉゝ∀・)\x038~キラ%s" % prefix.encode("utf-8"))

    @bones.event.handler(trigger="hue")
    def cmdHue(self, event):
        event.channel.msg("ヾ（´▽｀） \x038ＨＵＥ\x034ＨＵＥ\x0313ＨＵＥ")

    @bones.event.handler(trigger="huehue")
    def cmdHueHue(self, event):
        event.channel.msg(
            "ヾ（´▽｀） \x038ＨＵＥ\x034ＨＵＥ\x0313ＨＵＥ\x0312ＨＵＥ"
            "\x039ＨＵＥ\x034ＨＵＥ\x0313ＨＵＥ\x038ＨＵＥ\x039ＨＵＥ"
            "\x0311ＨＵＥＨＵＥ\x0312ＨＵＥ"
        )

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
        print("Error: Section 'storage' does not contain an 'sqlalchemy.url'",
              "key.")
        sys.exit(1)
    print("Connecting to '%s'..."
          % settings._sections["storage"]["sqlalchemy.url"])
    engine = engine_from_config(settings._sections["storage"], "sqlalchemy.")
    print "Creating tables..."
    from bones.modules.storage import Base
    Base.metadata.create_all(engine)
    print "Have a nice day!"
