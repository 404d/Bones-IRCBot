# -*- encoding: utf8 -*-
import sys
import logging
from ConfigParser import SafeConfigParser

from twisted.internet import reactor

from bones.bot import BonesBotFactory
from bones.modules import (
        MinecraftServerList,
        UselessResponses,
        Utilities,
    )

if __name__ == "__main__":
    log = logging.getLogger(__package__)
    settings = SafeConfigParser()
    settings.read(sys.argv[1])

    botFactory = BonesBotFactory(settings)

    serverHost = settings.get("server", "host")
    serverPort = int(settings.get("server", "port"))
    if settings.get("server", "useSSL") == "true":
        log.info("Connecting to server %s:+%i", serverHost, serverPort)
        try:
            from twisted.internet import ssl
        except ImportError:
            ex = Exception("Unmet dependency: pyOpenSSL not installed. This dependency needs to be installed before you can use SSL server connections")
            log.exception(ex)
            raise ex
        reactor.connectSSL(serverHost, serverPort, botFactory, ssl.ClientContextFactory())
    else:
        log.info("Connecting to server %s:%i", serverHost, serverPort)
        reactor.connectTCP(serverHost, serverPort, botFactory)
    reactor.run()
