import json
import logging
from typing import Any, Dict, List, Mapping, Optional
from urllib import parse

from homeassistant.const import STATE_OFF, STATE_ON, STATE_PROBLEM, STATE_UNKNOWN
from homeassistant.helpers.entity import Entity
import jsonrpc_base
from pykodi import Kodi

from .types import KodiConfig

_LOGGER = logging.getLogger(__name__)


class KodiMediaEntity(Entity):
    properties: List[str] = NotImplemented
    result_key: str = NotImplemented
    update_method: str = NotImplemented

    def __init__(self, kodi: Kodi, config: KodiConfig) -> None:
        super().__init__()
        self.kodi = kodi
        self.data = []
        self._state = None

        protocol = "https" if config["ssl"] else "http"
        auth = ""
        if config["username"] is not None and config["password"] is not None:
            auth = f"{config['username']}:{config['password']}@"
        self.base_web_url = (
            f"{protocol}://{auth}{config['host']}:{config['port']}/image/image%3A%2F%2F"
        )

    @property
    def state(self) -> Optional[str]:
        return self._state

    async def async_update(self) -> None:
        if not self.kodi._conn.connected:
            _LOGGER.debug("Kodi is not connected, skipping update.")
            return

        result = None
        try:
            result = await self.kodi.call_method(
                self.update_method, properties=self.properties
            )
        except jsonrpc_base.jsonrpc.ProtocolError as exc:
            error = exc.args[2]["error"]
            _LOGGER.error(
                "Run API method %s.%s(%s) error: %s",
                self.entity_id,
                self.update_method,
                self.properties,
                error,
            )
        except jsonrpc_base.jsonrpc.TransportError:
            _LOGGER.debug(
                "TransportError trying to run API method %s.%s(%s)",
                self.entity_id,
                self.update_method,
                self.properties,
            )
        except Exception:
            _LOGGER.exception("Error updating sensor, is kodi running?")
            self._state = STATE_OFF

        if result:
            self._handle_result(result)
        else:
            self._state = STATE_OFF

    def _handle_result(self, result) -> None:
        error = result.get("error")
        if error:
            _LOGGER.error(
                "Error while fetching %s: [%d] %s"
                % (self.result_key, error.get("code"), error.get("message"))
            )
            self._state = STATE_PROBLEM
            return

        new_data: List[Dict[str, Any]] = result.get(self.result_key, [])
        if not new_data:
            _LOGGER.warning(
                "No %s found after requesting data from Kodi, assuming empty."
                % self.result_key
            )
            self._state = STATE_UNKNOWN
            return

        self.data = new_data
        self._state = STATE_ON

    def get_web_url(self, path: str) -> str:
        if path.lower().startswith("http"):
            return path
        quoted_path = parse.quote(parse.quote(path, safe=""))
        return self.base_web_url + quoted_path


class KodiNextUpTVEntity(KodiMediaEntity):
    properties = [
        "art",
        "episode",
        "fanart",
        "firstaired",
        "playcount",
        "rating",
        "runtime",
        "season",
        "showtitle",
        "title",
    ]
    # Update this method to the appropriate Kodi method for "Next Up" episodes
    update_method = "VideoLibrary.GetTVShows"
    result_key = "tvshows"

    @property
    def unique_id(self) -> str:
        return "kodi_next_up_tv"

    @property
    def name(self) -> str:
        return "Kodi Next Up TV"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        attrs = {}
        card_json = [
            {
                "title_default": "$title",
                "line1_default": "$episode",
                "line2_default": "$firstaired",
                "line3_default": "$rating - $runtime",
                "line4_default": "$number",
                "icon": "mdi:eye-off",
            }
        ]
        for show in self.data:
            card = {
                "episode": show["title"],
                "fanart": "",
                "flag": show["playcount"] == 0,
                "number": "S{:0>2}E{:0>2}".format(show["season"], show["episode"]),
                "poster": "",
                "runtime": show["runtime"] // 60,
                "title": show["showtitle"],
            }
            rating = round(show["rating"], 1)
            if rating:
                rating = f"\N{BLACK STAR} {rating}"
            card["rating"] = rating
            fanart = show["art"].get("tvshow.fanart", "")
            poster = show["art"].get("tvshow.poster", "")
            if fanart:
                card["fanart"] = self.get_web_url(parse.unquote(fanart)[8:].strip("/"))
            if poster:
                card["poster"] = self.get_web_url(parse.unquote(poster)[8:].strip("/"))
            card_json.append(card)

        attrs["data"] = json.dumps(card_json)
        return attrs
