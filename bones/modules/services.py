import bones.event
from bones.bot import Module


class NickServ(Module):
    def __init__(self, *args, **kwargs):
        Module.__init__(self, *args, **kwargs)
        self._disabled = False
        if not self.settings.get("services", "nickserv.password"):
            self.log.error(
                "Configuration doesn't contain a NickServ password. Please "
                "add `nickserv.password` to `[services]` and make it a "
                "non-empty value."
            )
            self.log.error("NickServ module will be disabled.")
            self._disabled = True

    @bones.event.handler(event=bones.event.BotSignedOnEvent)
    def identifySignOn(self, event):
        if self._disabled:
            return
        # Make sure that we're supposed to identify now.
        if self.settings.get("services", "nickserv.waitForNotice",
                             default="true") != "false":
            return

        # We're good to go!
        self.log.info("Identifying with NickServ")
        event.client.msg(
            "NickServ",
            "IDENTIFY %s" % self.settings.get("services",
                                              "nickserv.password")
        )

    @bones.event.handler(event=bones.event.BotNoticeReceivedEvent)
    def identifyNotice(self, event):
        if self._disabled:
            return

        # Make sure that we're supposed to handle on notices.
        if self.settings.get("services", "nickserv.waitForNotice",
                             default="true") != "true":
            return

        # Make sure that we're supposed to identify now.
        if "IDENTIFY" in event.message.upper() \
                and bones.event.User(event.user, event.client) \
                .nickname.lower() == "nickserv":
            # We're good to go!
            self.log.info("Identifying with NickServ (triggered by notice)")
            event.client.msg(
                "NickServ",
                "IDENTIFY %s" %
                (self.settings.get("services", "nickserv.password"),)
            )


class HostServ(Module):

    def __init__(self, *args, **kwargs):
        Module.__init__(self, *args, **kwargs)
        self.channelJoinQueue = []
        self.haveVhost = False
        self.haveIdentified = False
        self.log.info(
            "HostServ module enabled, all joins will be cancelled until we "
            "have received a vhost."
        )

    @bones.event.handler(event=bones.event.BotSignedOnEvent)
    def cleanup(self, event):
        self.channelJoinQueue = []
        self.haveVhost = False
        self.haveIdentified = False

    @bones.event.handler(event=bones.event.BotPreJoinEvent)
    def preventUncloakedJoins(self, event):
        # One of the most important things we need to do is prevent
        # joining while we do not have a vhost
        if not self.haveVhost:
            self.log.debug("Queueing join to channel %s", event.channel)
            # Add channel to join queue
            self.channelJoinQueue.append(event.channel)
            # Cancel the event so that the bot won't join the channel
            event.isCancelled = True

    @bones.event.handler(event=bones.event.IRCUnknownCommandEvent)
    def manageReplies(self, event):
        # If the server is using cloaks, it will send a 396 while
        # giving us a cloak. Therefore we need to wait until we've
        # identified with services
        if event.command == "900":
            self.haveIdentified = True

        # Now that we've finally gotten our vhost, let's join all
        # those channels!
        elif event.command == "396" and self.haveIdentified:
            self.log.info("Received Vhost, joining all queued channels")
            # As we've got a vhost, we shouldn't prevent joins anymore.
            self.haveVhost = True
            while self.channelJoinQueue:
                event.client.join(self.channelJoinQueue.pop())
