import logging
log = logging.getLogger(__name__)

from sqlalchemy import engine_from_config
from sqlalchemy import (
    Column,
    Text,
    Integer,
    )
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import (
    sessionmaker,
    )

import bones.event
from bones.bot import Module

Base = declarative_base()


class Database(Module):

    def __init__(self, settings):
        self.settings = settings
        self.sessionmaker = None
        self.engine = None

    def new_session(self):
        return self.sessionmaker()

    @bones.event.handler(event=bones.event.BotInitializedEvent)
    def botReady(self, event):
        self.engine = engine_from_config(self.settings.data["storage"], "sqlalchemy.")
        log.debug("Connected to database")
        dbInitEvent = DatabaseInitializedEvent(self)
        bones.event.fire(event.factory.tag, dbInitEvent)
        self.sessionmaker = sessionmaker(bind=self.engine, autocommit=True)


class DatabaseInitializedEvent(bones.event.Event):
    def __init__(self, module):
        self.module = module
