"""Map URL host → Apify Actor id + input skeleton."""

from __future__ import annotations

from dataclasses import dataclass

from .route import is_video_url


@dataclass(frozen=True)
class ActorJob:
    actor_id: str
    run_input: dict
    platform: str


# Clockworks TikTok + official IG reel scraper (plan defaults).
_TIKTOK_ACTOR = "clockworks/tiktok-transcript-extractor"
_INSTAGRAM_ACTOR = "apify/instagram-reel-scraper"
_YOUTUBE_ACTOR = "codepoetry/youtube-transcript-ai-scraper"
_FALLBACK_ACTOR = "scrapier/tiktok-instagram-facebook-youtube-shorts-transcriber"


def classify_platform(url: str) -> str:
    u = url.lower()
    if "tiktok.com" in u or "vm.tiktok.com" in u or "vt.tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u:
        return "instagram"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "facebook.com" in u or "fb.watch" in u:
        return "facebook"
    if is_video_url(url):
        return "video_other"
    return "link"


def actor_for_url(url: str) -> ActorJob | None:
    """Return Apify job for video URLs; None for plain links (Karakeep-only)."""
    platform = classify_platform(url)
    if platform == "tiktok":
        # Prefer video scraper with STT when native subs missing.
        return ActorJob(
            actor_id="clockworks/tiktok-video-scraper",
            platform=platform,
            run_input={
                "postURLs": [url],
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
                "downloadSubtitlesOptions": "DOWNLOAD_AND_TRANSCRIBE_VIDEOS_WITHOUT_SUBTITLES",
            },
        )
    if platform == "instagram":
        return ActorJob(
            actor_id=_INSTAGRAM_ACTOR,
            platform=platform,
            run_input={
                "username": [url],
                "resultsLimit": 1,
                "includeTranscript": True,
            },
        )
    if platform == "youtube":
        return ActorJob(
            actor_id=_YOUTUBE_ACTOR,
            platform=platform,
            run_input={"startUrls": [{"url": url}], "enableAiFallback": True},
        )
    if platform in ("facebook", "video_other"):
        return ActorJob(
            actor_id=_FALLBACK_ACTOR,
            platform=platform,
            run_input={"start_urls": [{"url": url}], "language": "auto"},
        )
    return None
