"""
Refactor of the original SkipCourse tool.

Same functionality and API surface as the source file — this version focuses on
readability: type hints, a dispatch table instead of if/elif chains, dataclasses
for structured data, and centralized constants for the item-type sets.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Optional

import click
import httpx
from loguru import logger

from .coach.solver import CoachSolver
from .config import BASE_URL, CONFIG_FILE, DEFAULT_CONFIG, HEADERS, ensure_cookies, fetch_browser_cookies
from .session_utils import get_csrf_headers
from .watcher.watch import Watcher


BANNER = r"""
   ____  _    _         _____
  / ___|| | _(_)_ __   / ____|___  _   _ _ __ ___  ___
  \___ \| |/ / | '_ \ | |    / _ \| | | | '__/ __|/ _ \
   ___) |   <| | |_) || |___| (_) | |_| | |  \__ \  __/
  |____/|_|\_\_| .__/  \_____\___/ \__,_|_|  |___/\___|
               |_|
          built by Apurva Anand
"""


def _fmt_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s"


def _print_item_status(name: str, status: str, elapsed: float) -> None:
    """Compact one-line status: name, status, elapsed time — no course/module IDs."""
    symbol = {"done": "✔", "failed": "✘", "skip": "→"}.get(status, "•")
    color = {"done": "\033[32m", "failed": "\033[31m", "skip": "\033[33m"}.get(status, "")
    reset = "\033[0m"
    label = {"done": "done", "failed": "failed", "skip": "skipped"}.get(status, status)
    click.echo(f"{color}{symbol} {name:<60}{label:<10}{_fmt_seconds(elapsed)}{reset}")


# --- Item-type classification -------------------------------------------------

# Types that must be processed one-at-a-time (or are simply left for the human).
SEQUENTIAL_TYPES = {"discussionPrompt", "ungradedAssignment", "staffGraded", "phasedPeer"}

# Types explicitly left untouched — require genuine manual submission.
MANUAL_SKIP_TYPES = {"ungradedAssignment", "staffGraded", "discussionPrompt"}

MAX_WORKERS = 6


@dataclass
class VideoMetadata:
    can_skip: bool
    tracking_id: str


class CourseRunner:
    """Walks a Coursera course's item tree and processes each item via its handler."""

    def __init__(self, course_slug: str):
        self.course_slug = course_slug
        self.base_url = BASE_URL
        self.session = httpx.Client(timeout=60.0, follow_redirects=True)
        self.session.headers.update(HEADERS)
        self.session.cookies.update(ensure_cookies())

        self.user_id: Optional[str] = None
        self.course_id: Optional[str] = None
        self.failed_items: set[str] = set()

        # Dispatch table: item type -> handler. Built once auth is confirmed.
        self._handlers: dict[str, Callable[[dict], bool]] = {
            "lecture": self._handle_lecture,
            "supplement": self._handle_supplement,
            "coach": self._handle_coach,
            "ungradedWidget": self._handle_ungraded_widget,
            "ungradedLti": self._handle_ungraded_lti,
        }

        if not self._resolve_user_id():
            self._refresh_cookies()
            if not self._resolve_user_id():
                logger.error("Cookies are invalid. Log into Coursera in your browser, close it, and retry.")
                raise SystemExit

    # --- Auth -------------------------------------------------------------

    def _refresh_cookies(self) -> None:
        logger.warning("Session expired — re-fetching cookies from browser...")
        cookies = fetch_browser_cookies()
        if not cookies:
            return

        self.session.cookies.clear()
        self.session.cookies.update(cookies)

        cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else DEFAULT_CONFIG.copy()
        cfg["cookies"] = cookies
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

    def _resolve_user_id(self) -> bool:
        r = self.session.get(self.base_url + "adminUserPermissions.v1?q=my").json()
        try:
            self.user_id = r["elements"][0]["id"]
            logger.info(f"Authenticated as user: {self.user_id}")
        except KeyError:
            if r.get("errorCode"):
                logger.error(f"Auth error: {r['errorCode']}")
            return False
        return True

    # --- Course fetching ----------------------------------------------------

    def run(self) -> None:
        """Entry point: fetch course, then process items until nothing pending remains."""
        materials = self._fetch_course_materials()
        self.course_id = materials["elements"][0]["id"]
        all_items = materials["linked"]["onDemandCourseMaterialItems.v2"]

        click.echo(f"{len(all_items)} items found. Starting...\n")
        self._process_all_items(all_items)

    def _fetch_course_materials(self) -> dict:
        r = self.session.get(
            self.base_url + "onDemandCourseMaterials.v2/",
            params={
                "q": "slug",
                "slug": self.course_slug,
                "includes": "modules,lessons,passableItemGroups,passableItemGroupChoices,passableLessonElements,"
                            "items,tracks,gradePolicy,gradingParameters,embeddedContentMapping",
                "fields": "moduleIds,onDemandCourseMaterialModules.v1(name,slug,description,timeCommitment,"
                          "lessonIds,optional,learningObjectives),onDemandCourseMaterialLessons.v1(name,slug,"
                          "timeCommitment,elementIds,optional,trackId),onDemandCourseMaterialPassableItemGroups.v1("
                          "requiredPassedCount,passableItemGroupChoiceIds,trackId),"
                          "onDemandCourseMaterialPassableItemGroupChoices.v1(name,description,itemIds),"
                          "onDemandCourseMaterialPassableLessonElements.v1(gradingWeight,isRequiredForPassing),"
                          "onDemandCourseMaterialItems.v2(name,originalName,slug,timeCommitment,contentSummary,"
                          "isLocked,lockableByItem,itemLockedReasonCode,trackId,lockedStatus,itemLockSummary,"
                          "customDisplayTypenameOverride),onDemandCourseMaterialTracks.v1(passablesCount),"
                          "onDemandGradingParameters.v1(gradedAssignmentGroups),"
                          "contentAtomRelations.v1(embeddedContentSourceCourseId,subContainerId)",
                "showLockedItems": True,
            },
        )

        if r.status_code != 200:
            logger.error("Course fetch failed — check that you're enrolled in this course.")
            raise SystemExit

        return r.json()

    def _fetch_completed_item_ids(self) -> set[str]:
        r = self.session.get(
            self.base_url + f"onDemandCoursesProgress.v1/{self.user_id}~{self.course_id}",
            params={"fields": "gradedAssignmentGroupProgress"},
        )

        if r.status_code != 200:
            logger.debug(f"Progress fetch failed: {r.text}")
            return set()

        elements = r.json().get("elements") or []
        if not elements:
            return set()

        items = elements[0].get("items", {})
        return {item_id for item_id, progress in items.items() if progress.get("progressState") == "Completed"}

    # --- Scheduling loop ------------------------------------------------

    def _process_all_items(self, all_items: list[dict]) -> None:
        total = len(all_items)

        while True:
            completed = self._fetch_completed_item_ids()

            try:
                current_items = self._fetch_course_materials()["linked"]["onDemandCourseMaterialItems.v2"]
            except SystemExit:
                current_items = all_items

            pending = [item for item in current_items if item["id"] not in completed]
            if not pending:
                click.echo(f"\nAll {total} items completed.")
                return

            actionable = [
                item for item in pending
                if not item.get("isLocked", False) and item["id"] not in self.failed_items
            ]
            if not actionable:
                click.echo(f"\nStopped — {total - len(pending)}/{total} completed, {len(pending)} locked or failed.")
                return

            concurrent_batch = [i for i in actionable if i["contentSummary"]["typeName"] not in SEQUENTIAL_TYPES]
            sequential_batch = [i for i in actionable if i["contentSummary"]["typeName"] in SEQUENTIAL_TYPES]

            if concurrent_batch:
                self._run_concurrent_batch(concurrent_batch)
                continue

            self._run_single_item(sequential_batch[0])

    def _run_concurrent_batch(self, items: list[dict]) -> None:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(items))) as pool:
            futures = {pool.submit(self._timed_dispatch, item): item for item in items}
            for future in as_completed(futures):
                item = futures[future]
                self._collect_result(item, future)

    def _run_single_item(self, item: dict) -> None:
        start = time.monotonic()
        try:
            success = self._dispatch_item(item)
            elapsed = time.monotonic() - start
            if success:
                _print_item_status(item["name"], "done", elapsed)
            else:
                _print_item_status(item["name"], "failed", elapsed)
                self.failed_items.add(item["id"])
        except Exception:
            elapsed = time.monotonic() - start
            _print_item_status(item["name"], "failed", elapsed)
            logger.exception(f"Error processing item {item['id']}")
            self.failed_items.add(item["id"])

    def _timed_dispatch(self, item: dict) -> tuple[bool, float]:
        start = time.monotonic()
        success = self._dispatch_item(item)
        return success, time.monotonic() - start

    def _collect_result(self, item: dict, future) -> None:
        try:
            success, elapsed = future.result()
            _print_item_status(item["name"], "done" if success else "failed", elapsed)
            if not success:
                self.failed_items.add(item["id"])
        except Exception:
            _print_item_status(item["name"], "failed", 0.0)
            logger.exception(f"Error processing item {item['id']}")
            self.failed_items.add(item["id"])

    # --- Item dispatch ----------------------------------------------------

    def _dispatch_item(self, item: dict) -> bool:
        item_type = item["contentSummary"]["typeName"]

        if item_type in MANUAL_SKIP_TYPES:
            _print_item_status(item["name"], "skip", 0.0)
            return True

        handler = self._handlers.get(item_type)
        if handler is None:
            _print_item_status(item["name"], "skip", 0.0)
            return True

        return handler(item)

    def _handle_lecture(self, item: dict) -> bool:
        metadata = self._fetch_video_metadata(item["id"])
        return Watcher(self.session, item, metadata.__dict__, self.user_id, self.course_slug, self.course_id).watch_item()

    def _handle_supplement(self, item: dict) -> bool:
        r = self.session.post(
            self.base_url + "onDemandSupplementCompletions.v1",
            headers=get_csrf_headers(self.session),
            json={"courseId": self.course_id, "itemId": item["id"], "userId": int(self.user_id)},
        )
        return "Completed" in r.text

    def _handle_coach(self, item: dict) -> bool:
        return CoachSolver(self.session, self.user_id, self.course_id, item["id"]).solve()

    def _handle_ungraded_widget(self, item: dict) -> bool:
        item_id = item["id"]
        r = self.session.get(
            self.base_url + f"onDemandWidgetSessions.v1/{self.user_id}~{self.course_id}~{item_id}",
            params={"fields": "session,sessionId"},
        )
        if r.status_code != 200:
            logger.error(f"[item:{item_id}] Widget session fetch failed: {r.status_code}")
            return False

        try:
            session_id = r.json()["elements"][0]["sessionId"]
        except (KeyError, IndexError):
            logger.error(f"[item:{item_id}] Could not parse sessionId.")
            return False

        res = self.session.put(
            self.base_url + f"onDemandWidgetProgress.v1/{self.user_id}~{self.course_id}~{item_id}",
            headers=get_csrf_headers(self.session),
            json={"sessionId": session_id, "progressState": "Completed"},
        )
        return 200 <= res.status_code < 300

    def _handle_ungraded_lti(self, item: dict) -> bool:
        r = self.session.post(
            self.base_url + "rest/v1/lti/ungradedLaunches",
            headers=get_csrf_headers(self.session),
            json={
                "courseId": self.course_id,
                "itemId": item["id"],
                "learnerId": int(self.user_id),
                "markItemCompleted": True,
            },
        )
        return 200 <= r.status_code < 300

    def _fetch_video_metadata(self, item_id: str) -> VideoMetadata:
        r = self.session.get(
            self.base_url + f"onDemandLectureVideos.v1/{self.course_id}~{item_id}",
            params={"includes": "video", "fields": "disableSkippingForward,startMs,endMs"},
        ).json()

        return VideoMetadata(
            can_skip=not r["elements"][0]["disableSkippingForward"],
            tracking_id=r["linked"]["onDemandVideos.v1"][0]["id"],
        )


@logger.catch
@click.command()
@click.argument("slug")
def main(slug: str) -> None:
    CourseRunner(slug).run()


if __name__ == "__main__":
    main()