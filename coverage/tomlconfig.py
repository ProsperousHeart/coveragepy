# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0
# For details: https://github.com/nedbat/coveragepy/blob/master/NOTICE.txt

"""TOML configuration support for coverage.py"""

import os
import re

from coverage import env
from coverage.exceptions import ConfigError
from coverage.misc import import_third_party, substitute_variables


if env.PYVERSION >= (3, 11, 0, "alpha", 7):
    import tomllib      # pylint: disable=import-error
else:
    # TOML support on Python 3.10 and below is an install-time extra option.
    tomllib = import_third_party("tomli")


class TomlDecodeError(Exception):
    """An exception class that exists even when toml isn't installed."""
    pass


class TomlConfigParser:
    """TOML file reading with the interface of HandyConfigParser."""

    # This class has the same interface as config.HandyConfigParser, no
    # need for docstrings.
    # pylint: disable=missing-function-docstring

    def __init__(self, our_file):
        self.our_file = our_file
        self.data = None

    def read(self, filenames):
        # RawConfigParser takes a filename or list of filenames, but we only
        # ever call this with a single filename.
        assert isinstance(filenames, (bytes, str, os.PathLike))
        filename = os.fspath(filenames)

        try:
            with open(filename, encoding='utf-8') as fp:
                toml_text = fp.read()
        except OSError:
            return []
        if tomllib is not None:
            try:
                self.data = tomllib.loads(toml_text)
            except tomllib.TOMLDecodeError as err:
                raise TomlDecodeError(str(err)) from err
            return [filename]
        else:
            has_toml = re.search(r"^\[tool\.coverage(\.|])", toml_text, flags=re.MULTILINE)
            if self.our_file or has_toml:
                # Looks like they meant to read TOML, but we can't read it.
                msg = "Can't read {!r} without TOML support. Install with [toml] extra"
                raise ConfigError(msg.format(filename))
            return []

    def _get_section(self, section):
        """Get a section from the data.

        Arguments:
            section (str): A section name, which can be dotted.

        Returns:
            name (str): the actual name of the section that was found, if any,
                or None.
            data (str): the dict of data in the section, or None if not found.

        """
        prefixes = ["tool.coverage."]
        for prefix in prefixes:
            real_section = prefix + section
            parts = real_section.split(".")
            try:
                data = self.data[parts[0]]
                for part in parts[1:]:
                    data = data[part]
            except KeyError:
                continue
            break
        else:
            return None, None
        return real_section, data

    def _get(self, section, option):
        """Like .get, but returns the real section name and the value."""
        name, data = self._get_section(section)
        if data is None:
            raise ConfigError(f"No section: {section!r}")
        try:
            value = data[option]
        except KeyError:
            raise ConfigError(f"No option {option!r} in section: {name!r}") from None
        return name, value

    def _get_single(self, section, option):
        """Get a single-valued option.

        Performs environment substitution if the value is a string. Other types
        will be converted later as needed.
        """
        name, value = self._get(section, option)
        if isinstance(value, str):
            value = substitute_variables(value, os.environ)
        return name, value

    def has_option(self, section, option):
        _, data = self._get_section(section)
        if data is None:
            return False
        return option in data

    def real_section(self, section):
        name, _ = self._get_section(section)
        return name

    def has_section(self, section):
        name, _ = self._get_section(section)
        return bool(name)

    def options(self, section):
        _, data = self._get_section(section)
        if data is None:
            raise ConfigError(f"No section: {section!r}")
        return list(data.keys())

    def get_section(self, section):
        _, data = self._get_section(section)
        return data

    def get(self, section, option):
        _, value = self._get_single(section, option)
        return value

    def _check_type(self, section, option, value, type_, converter, type_desc):
        """Check that `value` has the type we want, converting if needed.

        Returns the resulting value of the desired type.
        """
        if isinstance(value, type_):
            return value
        if isinstance(value, str) and converter is not None:
            try:
                return converter(value)
            except Exception as e:
                raise ValueError(
                    f"Option [{section}]{option} couldn't convert to {type_desc}: {value!r}"
                ) from e
        raise ValueError(
            f"Option [{section}]{option} is not {type_desc}: {value!r}"
        )

    def getboolean(self, section, option):
        name, value = self._get_single(section, option)
        bool_strings = {"true": True, "false": False}
        return self._check_type(name, option, value, bool, bool_strings.__getitem__, "a boolean")

    def _get_list(self, section, option):
        """Get a list of strings, substituting environment variables in the elements."""
        name, values = self._get(section, option)
        values = self._check_type(name, option, values, list, None, "a list")
        values = [substitute_variables(value, os.environ) for value in values]
        return name, values

    def getlist(self, section, option):
        _, values = self._get_list(section, option)
        return values

    def getregexlist(self, section, option):
        name, values = self._get_list(section, option)
        for value in values:
            value = value.strip()
            try:
                re.compile(value)
            except re.error as e:
                raise ConfigError(f"Invalid [{name}].{option} value {value!r}: {e}") from e
        return values

    def getint(self, section, option):
        name, value = self._get_single(section, option)
        return self._check_type(name, option, value, int, int, "an integer")

    def getfloat(self, section, option):
        name, value = self._get_single(section, option)
        if isinstance(value, int):
            value = float(value)
        return self._check_type(name, option, value, float, float, "a float")
