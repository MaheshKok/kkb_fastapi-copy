# !/usr/bin/env python
# encoding: utf-8
import logging
import logging.config
import os
import pathlib

import tomli as toml

from app.utils.constants import ConfigFile


class Config:
    """
    This class loads configuration data from a TOML file.

    It provides a convenient method to override settings via
    environment variables.

    """

    @classmethod
    def load_path(cls, path: pathlib.Path, **kwargs) -> dict:
        """
        Load TOML data from a file path.

        """
        text = path.read_text()
        return cls.load_string(text, **kwargs)

    @classmethod
    def load_string(cls, text: str, **kwargs) -> dict:
        """
        Load TOML data from a string.

        """
        try:
            return toml.loads(text, **kwargs)
        except Exception as e:
            logging.getLogger("daffi.config").exception(e)
            return {}

    def __init__(self, path: pathlib.Path, **kwargs):
        self.path = path
        self.headings = set(self.load_path(path, **kwargs).keys()) if path else set()
        self.data = self.load_path(path, **kwargs) if path else {}

    def update(self, data, sep="_", **kwargs):
        """
        Update nested configuration data from a flat dictionary.

        The separator character is used to determine the data hierarchy, eg:
        a setting called DB_PORT will be stored as {"DB": {"PORT": ...}}.

        """
        items = [(k, v) for k, v in data.items() if k.partition(sep)[0] in self.headings]
        items.extend(
            [
                (k.lower(), v)
                for k, v in data.items()
                if k.partition(sep)[0].lower() in self.headings
            ]
        )
        for k, v in items:
            nodes = k.split(sep)[:-1]
            leaf = k.split(sep)[-1]
            n = self.data
            for node in nodes:
                n = n.setdefault(node, {})

            try:
                n.update(toml.loads(f"{leaf} = {v}"))
            except Exception:
                n.update(toml.loads(f'{leaf} = "{v}"'))

        return self

    def configure_logging(self, table="logging"):
        """
        Configure the logging system from data.

        """
        logging.config.dictConfig(self.data.get(table, {"version": 1}))
        return self


def get_config(config_file: str = ConfigFile.PRODUCTION) -> Config:
    config_file_path = os.path.join(
        pathlib.Path(__file__).parent.parent.absolute(), "cfg", config_file
    )
    return Config(pathlib.Path(config_file_path)).update(os.environ).configure_logging()
