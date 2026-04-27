from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import threading
import webbrowser
from http import HTTPStatus
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from downloader_app.browser_config import (
    BrowserConfigError,
    browser_config_manager,
    detect_profiles_for_browser_path,
)
from downloader_app.browser_session import browser_session
from downloader_app.cache_manager import CacheManagerError, cache_manager
from downloader_app.google_auth import GoogleAuthError, google_oauth
from downloader_app.jobs import manager
from downloader_app.runtime import bundled_path
from downloader_app.sheets import SheetParseError, normalize_sequence_range
from downloader_app.story_pipeline import StoryPipelineError, story_pipeline
from downloader_app.tts_manager import tts_manager
from downloader_app.updater import updater, UpdateError


STATIC_DIR = bundled_path("static")
WEB_DIST_DIR = bundled_path("web", "dist")


class AppHandler(BaseHTTPRequestHandler):
    server_version = "VideoDownloader/0.2"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            self._serve_app_index()
            return

        if path == "/api/bootstrap":
            self._send_json(
                {
                    "authStatus": browser_session.status(),
                    "settings": manager.get_settings(),
                    "batchSummaries": manager.list_batch_summaries(),
                    "activeBatchId": manager.get_active_batch_id(),
                }
            )
            return

        if path == "/api/tts/bootstrap":
            self._send_json(tts_manager.get_bootstrap())
            return

        if path == "/api/events":
            self._serve_events(query)
            return

        if path == "/api/story/bootstrap":
            self._send_json(story_pipeline.get_bootstrap())
            return

        if path == "/api/cache/bootstrap":
            self._send_json(cache_manager.get_bootstrap())
            return

        if path == "/api/story/gems":
            self._send_json(story_pipeline.list_available_gems())
            return

        if path == "/api/story/session/status":
            refresh = self._single_query_value(query, "refresh") == "1"
            self._send_json(story_pipeline.get_session_status(refresh=refresh))
            return

        if path == "/api/story/file":
            raw_path = self._single_query_value(query, "path")
            if not raw_path:
                self._send_json({"error": "path is required."}, status=HTTPStatus.BAD_REQUEST)
                return
            self._serve_story_file(raw_path)
            return

        if path == "/api/story/videos":
            self._send_json(
                story_pipeline.list_video_summaries(
                    status=self._single_query_value(query, "status"),
                    limit=self._query_int(query, "limit"),
                )
            )
            return

        if path == "/api/story/events":
            self._serve_story_events(query)
            return

        if path == "/api/batches":
            self._send_json(
                manager.list_batch_summaries(
                    status=self._single_query_value(query, "status"),
                    query=self._single_query_value(query, "q"),
                    limit=self._query_int(query, "limit"),
                )
            )
            return

        if path == "/api/settings":
            self._send_json(manager.get_settings())
            return

        if path == "/api/tts/session/status":
            refresh = self._single_query_value(query, "refresh") == "1"
            self._send_json(tts_manager.get_session_status(refresh=refresh))
            return

        if path == "/api/tts/batches":
            self._send_json(tts_manager.list_batch_summaries())
            return

        if path == "/api/tts/voices":
            try:
                refresh = self._single_query_value(query, "refresh") == "1"
                self._send_json(tts_manager.list_available_voices(refresh=refresh))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/tts/audio/"):
            parts = path.rstrip("/").split("/")
            if len(parts) != 6:
                self._send_json({"error": "Audio not found."}, status=HTTPStatus.NOT_FOUND)
                return
            batch_id = parts[4]
            take_id = parts[5]
            audio_path = tts_manager.resolve_take_path(batch_id, take_id)
            if audio_path is None:
                self._send_json({"error": "Audio not found."}, status=HTTPStatus.NOT_FOUND)
                return
            content_type, _ = mimetypes.guess_type(str(audio_path))
            self._serve_file(audio_path, content_type or "audio/mpeg")
            return

        if path.startswith("/api/tts/batches/"):
            batch_id = path.split("/")[-1]
            batch = tts_manager.get_batch_detail(batch_id)
            if batch is None:
                self._send_json({"error": "TTS batch not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(batch)
            return

        if path.startswith("/api/story/videos/"):
            video_id = path.split("/")[-1]
            video = story_pipeline.get_video_detail(video_id)
            if video is None:
                self._send_json({"error": "Story video not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(video)
            return

        if path == "/api/google/auth-status":
            self._send_json(google_oauth.status())
            return

        if path == "/api/browser-session/status":
            self._send_json(browser_session.status())
            return

        if path == "/api/browser-config":
            self._send_json(browser_config_manager.get_all())
            return

        if path == "/api/system/updater/check":
            try:
                self._send_json(updater.check_for_updates())
            except UpdateError as e:
                self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/batches/"):
            batch_id = path.split("/")[-1]
            batch = manager.get_batch_detail(batch_id)
            if batch is None:
                self._send_json({"error": "Batch not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(batch)
            return

        if path == "/oauth2/callback":
            self._handle_google_callback(parsed.query)
            return

        if self._serve_frontend_asset(path):
            return

        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        if path == "/api/google/login":
            try:
                authorization_url = google_oauth.start_auth(self._base_url())
            except GoogleAuthError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"authorization_url": authorization_url})
            return

        if path == "/api/google/logout":
            google_oauth.logout()
            self._send_json({"ok": True})
            return

        if path == "/api/settings":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(manager.update_settings(payload))
            return

        if path == "/api/browser-config":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return

            try:
                self._send_json(browser_config_manager.update(payload))
            except BrowserConfigError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/browser-config/profiles":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return

            feature = str(payload.get("feature", "")).strip().lower()
            browser_path = str(payload.get("browser_path", "")).strip()
            profile_name = str(payload.get("profile_name", "")).strip()
            try:
                self._send_json(
                    detect_profiles_for_browser_path(
                        feature=feature,
                        browser_path=browser_path,
                        profile_name=profile_name,
                    )
                )
            except BrowserConfigError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/story/settings":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return

            try:
                self._send_json(story_pipeline.update_settings(payload))
            except StoryPipelineError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/story/global-prompt":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return

            prompt = str(payload.get("prompt", ""))
            try:
                self._send_json(story_pipeline.update_global_prompt(prompt))
            except StoryPipelineError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/story/session/open-login":
            try:
                self._send_json(story_pipeline.open_login())
            except StoryPipelineError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/story/videos/import":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return

            try:
                self._send_json(story_pipeline.import_manifest(payload), status=HTTPStatus.CREATED)
            except StoryPipelineError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/story/videos/scan-folder":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return

            try:
                self._send_json(story_pipeline.import_from_folder(payload), status=HTTPStatus.CREATED)
            except StoryPipelineError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/story/videos/") and (path.endswith("/run") or path.endswith("/pause") or path.endswith("/resume") or path.endswith("/cancel")):
            parts = path.strip("/").split("/")
            if len(parts) != 5:
                self._send_json({"error": "Story video not found."}, status=HTTPStatus.NOT_FOUND)
                return

            video_id = parts[3]
            action = parts[4]
            try:
                if action == "pause":
                    self._send_json(story_pipeline.pause_video(video_id))
                elif action == "cancel":
                    self._send_json(story_pipeline.cancel_video(video_id))
                else:
                    self._send_json(story_pipeline.run_video(video_id))
            except StoryPipelineError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/story/actions":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return

            try:
                self._send_json(story_pipeline.apply_action(payload))
            except StoryPipelineError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/story/videos/") and path.endswith("/export"):
            video_id = path.split("/")[-2]
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return
            destination_dir = str(payload.get("destination_dir", "")).strip()
            step_ids = payload.get("step_ids")
            if not destination_dir:
                self._send_json({"error": "destination_dir is required."}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(
                    story_pipeline.export_selected(
                        video_id=video_id,
                        destination_dir=destination_dir,
                        step_ids=step_ids,
                    )
                )
            except StoryPipelineError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/cache/clear":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return
            cache_id = str(payload.get("cache_id", "")).strip()
            if not cache_id:
                self._send_json({"error": "cache_id is required."}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(cache_manager.clear(cache_id))
            except CacheManagerError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/sheets/preview":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return

            sheet_url = str(payload.get("sheet_url", "")).strip()
            if not sheet_url:
                self._send_json({"error": "sheet_url is required."}, status=HTTPStatus.BAD_REQUEST)
                return

            try:
                sequence_start, sequence_end = normalize_sequence_range(
                    payload.get("sequence_start"),
                    payload.get("sequence_end"),
                )
                self._send_json(
                    manager.preview_sheet(
                        sheet_url,
                        sequence_start=sequence_start,
                        sequence_end=sequence_end,
                    )
                )
            except SheetParseError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/tts/sheets/preview":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return

            sheet_url = str(payload.get("sheet_url", "")).strip()
            if not sheet_url:
                self._send_json({"error": "sheet_url is required."}, status=HTTPStatus.BAD_REQUEST)
                return

            try:
                sequence_start, sequence_end = normalize_sequence_range(
                    payload.get("sequence_start"),
                    payload.get("sequence_end"),
                )
                self._send_json(
                    tts_manager.preview_sheet(
                        sheet_url,
                        text_column=str(payload.get("text_column", "")).strip() or None,
                        sequence_start=sequence_start,
                        sequence_end=sequence_end,
                    )
                )
            except SheetParseError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/tts/session/open-login":
            self._send_json(tts_manager.open_login())
            return

        if path == "/api/browser-session/open-login":
            self._send_json(browser_session.open_login())
            return

        if path == "/api/browser-session/refresh":
            browser_session.invalidate_cache()
            self._send_json(browser_session.status())
            return

        if path == "/api/browser-session/scrape-platform-cookies":
            try:
                payload = self._read_json_body()
                platform_id = str(payload.get("platform", "")).strip()
                if not platform_id:
                    self._send_json({"error": "platform is required."}, status=HTTPStatus.BAD_REQUEST)
                    return
                
                cookies = browser_session.extract_platform_cookies(platform_id)
                self._send_json({"cookies": cookies})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/system/choose-folder":
            try:
                folder_path = self._choose_folder()
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"path": folder_path})
            return

        if path == "/api/system/choose-browser":
            try:
                browser_path = self._choose_browser()
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"path": browser_path})
            return

        if path == "/api/system/updater/apply":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                updater.apply_update(payload.get("downloadUrl", ""))
                self._send_json({"status": "ok"})
            except UpdateError as e:
                self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as e:
                self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/system/open-folder":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return
            folder_path = str(payload.get("path", "")).strip()
            if not folder_path:
                self._send_json({"error": "path is required."}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                self._open_folder(folder_path)
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"ok": True})
            return

        if path == "/api/tts/batches":
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return

            sheet_url = str(payload.get("sheet_url", "")).strip()
            if not sheet_url:
                self._send_json({"error": "sheet_url is required."}, status=HTTPStatus.BAD_REQUEST)
                return

            try:
                requested_channel_prefix = str(payload.get("channelPrefix", "")).strip()
                default_channel_prefix = str(manager.get_settings().get("channel_prefix", "")).strip()
                sequence_start, sequence_end = normalize_sequence_range(
                    payload.get("sequence_start"),
                    payload.get("sequence_end"),
                )
                batch = tts_manager.create_batch(
                    sheet_url=sheet_url,
                    voice_query=str(payload.get("voice_query", "")).strip(),
                    voice_id=str(payload.get("voice_id", "")).strip() or None,
                    voice_name=str(payload.get("voice_name", "")).strip() or None,
                    model_family=str(payload.get("model_family", "")).strip(),
                    take_count=int(payload.get("take_count", 1)),
                    retry_count=int(payload.get("retry_count", 1)),
                    worker_count=int(payload.get("worker_count", 1)),
                    headless=bool(payload.get("headless", False)),
                    filename_prefix=str(payload.get("filenamePrefix", "")).strip() or None,
                    channel_prefix=requested_channel_prefix or default_channel_prefix or None,
                    tag_text=str(payload.get("tag_text", "")).strip(),
                    text_column=str(payload.get("text_column", "")).strip() or None,
                    sequence_start=sequence_start,
                    sequence_end=sequence_end,
                )
            except SheetParseError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(batch, status=HTTPStatus.CREATED)
            return

        if path.startswith("/api/tts/batches/") and (path.endswith("/pause") or path.endswith("/resume")):
            parts = path.strip("/").split("/")
            if len(parts) != 5:
                self._send_json({"error": "TTS batch not found."}, status=HTTPStatus.NOT_FOUND)
                return
            batch_id = parts[3]
            action = parts[4]
            try:
                if action == "pause":
                    self._send_json(tts_manager.pause_batch(batch_id))
                else:
                    self._send_json(tts_manager.resume_batch(batch_id))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/tts/batches/") and path.endswith("/cancel"):
            batch_id = path.split("/")[-2]
            try:
                self._send_json(tts_manager.cancel_batch(batch_id))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/tts/batches/") and path.endswith("/pick"):
            batch_id = path.split("/")[-2]
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(
                    tts_manager.pick_take(
                        batch_id=batch_id,
                        item_id=str(payload.get("item_id", "")).strip(),
                        take_id=str(payload.get("take_id", "")).strip(),
                    )
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/tts/batches/") and path.endswith("/retry-failed"):
            batch_id = path.split("/")[-2]
            try:
                self._send_json(tts_manager.retry_failed(batch_id))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/tts/batches/") and "/items/" in path and path.endswith("/retry"):
            parts = path.strip("/").split("/")
            if len(parts) != 7:
                self._send_json({"error": "TTS item not found."}, status=HTTPStatus.NOT_FOUND)
                return
            batch_id = parts[3]
            item_id = parts[5]
            try:
                self._send_json(tts_manager.retry_item(batch_id, item_id))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/tts/batches/") and path.endswith("/export"):
            batch_id = path.split("/")[-2]
            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
                return
            destination_dir = str(payload.get("destination_dir", "")).strip()
            item_ids = payload.get("item_ids") or []
            if not destination_dir:
                self._send_json({"error": "destination_dir is required."}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                self._send_json(
                    tts_manager.export_selected(
                        batch_id=batch_id,
                        item_ids=[str(item_id) for item_id in item_ids],
                        destination_dir=destination_dir,
                    )
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/batches/") and (path.endswith("/pause") or path.endswith("/resume")):
            parts = path.strip("/").split("/")
            if len(parts) != 4:
                self._send_json({"error": "Batch not found."}, status=HTTPStatus.NOT_FOUND)
                return
            batch_id = parts[2]
            action = parts[3]
            try:
                if action == "pause":
                    self._send_json(manager.pause_batch(batch_id))
                else:
                    self._send_json(manager.resume_batch(batch_id))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/batches/") and path.endswith("/cancel"):
            batch_id = path.split("/")[-2]
            try:
                self._send_json(manager.cancel_batch(batch_id))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path.startswith("/api/batches/") and path.endswith("/retry-failed"):
            batch_id = path.split("/")[-2]
            try:
                self._send_json(manager.retry_failed(batch_id))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if path != "/api/batches":
            self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json({"error": "Body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
            return

        sheet_url = str(payload.get("sheet_url", "")).strip()
        if not sheet_url:
            self._send_json({"error": "sheet_url is required."}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            sequence_start, sequence_end = normalize_sequence_range(
                payload.get("sequence_start"),
                payload.get("sequence_end"),
            )
            batch = manager.create_batch(
                sheet_url,
                settings_payload=payload.get("settings"),
                sequence_start=sequence_start,
                sequence_end=sequence_end,
            )
        except SheetParseError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._send_json(manager.get_batch_detail(batch.id), status=HTTPStatus.CREATED)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
        return json.loads(raw_body or "{}")

    def _single_query_value(self, query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key)
        if not values:
            return None
        value = str(values[0]).strip()
        return value or None

    def _query_int(self, query: dict[str, list[str]], key: str) -> int | None:
        value = self._single_query_value(query, key)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _base_url(self) -> str:
        host = self.headers.get("Host", "127.0.0.1:8765")
        return f"http://{host}"

    def _handle_google_callback(self, raw_query: str) -> None:
        query = parse_qs(raw_query)
        if "error" in query and query["error"]:
            message = query["error"][0]
            self._send_html(
                self._oauth_result_html(False, f"Dang nhap Google that bai: {message}"),
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            result = google_oauth.handle_callback(
                current_url=f"{self._base_url()}{self.path}",
                base_url=self._base_url(),
            )
        except GoogleAuthError as exc:
            self._send_html(
                self._oauth_result_html(False, str(exc)),
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        email = result.get("email")
        message = (
            f"Dang nhap thanh cong voi {email}. Dang quay lai app..."
            if email
            else "Dang nhap Google thanh cong. Dang quay lai app..."
        )
        self._send_html(self._oauth_result_html(True, message))

    def _serve_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.exists():
            self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
            return

        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_story_file(self, raw_path: str) -> None:
        file_path = Path(raw_path).expanduser()
        if not file_path.is_absolute():
            file_path = (Path.cwd() / file_path).resolve()
        else:
            file_path = file_path.resolve()

        if not file_path.exists() or not file_path.is_file():
            self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
            return

        content_type, _ = mimetypes.guess_type(str(file_path))
        if not content_type or not content_type.startswith("image/"):
            self._send_json({"error": "Only image files are supported."}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_file(file_path, content_type)

    def _serve_app_index(self) -> None:
        if (WEB_DIST_DIR / "index.html").exists():
            self._serve_file(WEB_DIST_DIR / "index.html", "text/html; charset=utf-8")
            return
        self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")

    def _serve_frontend_asset(self, path: str) -> bool:
        if path.startswith("/api/"):
            return False

        for root in (WEB_DIST_DIR, STATIC_DIR):
            if not root.exists():
                continue

            candidate = (root / path.lstrip("/")).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                continue

            if candidate.exists() and candidate.is_file():
                content_type, _ = mimetypes.guess_type(str(candidate))
                if content_type and content_type.startswith("text/"):
                    content_type = f"{content_type}; charset=utf-8"
                self._serve_file(candidate, content_type or "application/octet-stream")
                return True

        if WEB_DIST_DIR.exists():
            self._serve_app_index()
            return True
        return False

    def _serve_events(self, query: dict[str, list[str]]) -> None:
        last_event_id = self._query_int(query, "lastEventId") or 0

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            self._write_sse_event(
                {
                    "type": "connected",
                    "activeBatchId": manager.get_active_batch_id(),
                },
                event_id=last_event_id,
            )
            while True:
                events = manager.wait_for_events(after_id=last_event_id, timeout=15.0)
                if not events:
                    try:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                    except OSError:
                        return
                    continue

                for event in events:
                    last_event_id = int(event["id"])
                    self._write_sse_event(event, event_id=last_event_id)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def _serve_story_events(self, query: dict[str, list[str]]) -> None:
        last_event_id = self._query_int(query, "lastEventId") or 0

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            self._write_sse_event(
                {
                    "type": "connected",
                    "activeVideoId": story_pipeline.get_bootstrap().get("activeVideoId"),
                },
                event_id=last_event_id,
            )
            while True:
                events = story_pipeline.wait_for_events(after_id=last_event_id, timeout=15.0)
                if not events:
                    try:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                    except OSError:
                        return
                    continue

                for event in events:
                    last_event_id = int(event["id"])
                    self._write_sse_event(event, event_id=last_event_id)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def _write_sse_event(self, payload: dict, event_id: int) -> None:
        body = json.dumps(payload, ensure_ascii=False)
        self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
        self.wfile.write(f"event: {payload.get('type', 'message')}\n".encode("utf-8"))
        self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _oauth_result_html(self, success: bool, message: str) -> str:
        title = "Google Connected" if success else "Google Auth Failed"
        tone = "#6fe3a1" if success else "#ff6b6b"
        return f"""<!doctype html>
<html lang="vi">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <meta http-equiv="refresh" content="2;url=/" />
    <style>
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #101114;
        color: #f4f3ef;
        font-family: "Avenir Next", "Trebuchet MS", sans-serif;
      }}
      .card {{
        width: min(520px, calc(100vw - 32px));
        padding: 28px;
        border-radius: 24px;
        background: rgba(18, 20, 25, 0.94);
        border: 1px solid rgba(255, 255, 255, 0.08);
      }}
      .pill {{
        display: inline-block;
        padding: 8px 12px;
        border-radius: 999px;
        background: {tone};
        color: #151515;
        font-weight: 700;
      }}
      a {{
        color: #d6e3ff;
      }}
    </style>
  </head>
  <body>
    <div class="card">
      <p class="pill">{title}</p>
      <h1>{message}</h1>
      <p>Neu trang khong tu quay lai, hay bam <a href="/">ve app</a>.</p>
    </div>
  </body>
</html>"""

    def _choose_folder(self) -> str:
        from downloader_app.runtime import get_ui_bridge
        bridge = get_ui_bridge()
        if bridge:
            try:
                folder = bridge.choose_folder()
                if not folder:
                    raise RuntimeError("Khong chon duoc folder.")
                return folder
            except Exception as exc:
                print(f"Bridge choose_folder error: {exc}")
                # Fallback to other methods

        if sys.platform == "darwin":
            completed = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'POSIX path of (choose folder with prompt "Chon thu muc")',
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "Khong chon duoc folder.").strip()
                raise RuntimeError(message)

            folder = completed.stdout.strip()
            if not folder:
                raise RuntimeError("Khong nhan duoc duong dan folder.")
            return folder

        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:
            raise RuntimeError("Khong mo duoc folder picker. Hay nhap duong dan thu cong.") from exc

        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass

        try:
            folder = filedialog.askdirectory(title="Chon thu muc")
        finally:
            root.destroy()

        if not folder:
            raise RuntimeError("Khong nhan duoc duong dan folder.")
        return folder

    def _open_folder(self, folder_path: str) -> None:
        path = Path(folder_path).expanduser()
        if not path.exists():
            raise RuntimeError("Folder khong ton tai.")

        if sys.platform == "darwin":
            command = ["open", str(path)]
        elif sys.platform.startswith("linux"):
            command = ["xdg-open", str(path)]
        elif sys.platform == "win32":
            command = ["explorer", str(path)]
        else:
            raise RuntimeError("Nen tang hien tai chua ho tro open folder.")

        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Khong the mo folder.").strip()
            raise RuntimeError(message)

    def _choose_browser(self) -> str:
        from downloader_app.runtime import get_ui_bridge

        bridge = get_ui_bridge()
        if bridge:
            try:
                browser_path = bridge.choose_browser()
                if not browser_path:
                    raise RuntimeError("Khong chon duoc browser.")
                return browser_path
            except Exception as exc:
                print(f"Bridge choose_browser error: {exc}")

        if sys.platform == "darwin":
            completed = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'POSIX path of (choose application with prompt "Chon trinh duyet")',
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "Khong chon duoc browser.").strip()
                raise RuntimeError(message)
            browser_path = completed.stdout.strip()
            if not browser_path:
                raise RuntimeError("Khong nhan duoc duong dan browser.")
            return browser_path

        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:
            raise RuntimeError("Khong mo duoc browser picker.") from exc

        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass

        try:
            filetypes = [("Applications", "*.exe *.app"), ("All files", "*.*")]
            browser_path = filedialog.askopenfilename(
                title="Chon trinh duyet",
                filetypes=filetypes,
            )
        finally:
            root.destroy()

        if not browser_path:
            raise RuntimeError("Khong nhan duoc duong dan browser.")
        return browser_path


# Expected errors when a client disconnects mid-stream (Windows/Linux/Mac).
_CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


class _QuietHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that suppresses noisy client-disconnect tracebacks."""

    def handle_error(self, request, client_address):  # noqa: ARG002
        exc = sys.exc_info()[1]
        if isinstance(exc, _CLIENT_DISCONNECT_ERRORS):
            return
        # For genuine unexpected errors, keep the default behaviour.
        traceback.print_exc()


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = _QuietHTTPServer((host, port), AppHandler)
    app_url = f"http://{host}:{port}"
    print(f"Server running at {app_url}")
    if os.environ.get("VIDEO_DOWNLOADER_NO_BROWSER", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        threading.Timer(0.6, lambda: webbrowser.open(app_url, new=2)).start()
    server.serve_forever()
