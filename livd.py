#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
livd - LinkedIn Video Downloader
A simple yet complete command-line downloader for LinkedIn videos.

Examples:
    python livd.py "https://www.linkedin.com/posts/..." -q 1080
    python livd.py -f links.txt -o ./videos --cookies-from-browser chrome
    python livd.py "URL" --audio --subs en
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

try:
    import yt_dlp
    from yt_dlp.utils import DownloadError
except ImportError:
    sys.exit("yt-dlp is not installed. Run:  pip install -U yt-dlp")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

QUALITY = {
    "best": "bv*+ba/b",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]/b",
    "720": "bv*[height<=720]+ba/b[height<=720]/b",
    "480": "bv*[height<=480]+ba/b[height<=480]/b",
    "360": "bv*[height<=360]+ba/b[height<=360]/b",
    "worst": "wv*+wa/w",
}

DEFAULT_TEMPLATE = (
    "%(uploader_id,uploader|linkedin)s/"
    "%(upload_date>%Y-%m-%d)s - %(title).100B [%(id)s].%(ext)s"
)


# ---------------------------------------------------------------- helpers
def clean_url(url: str) -> str:
    """Strip tracking parameters and surrounding whitespace/quotes."""
    url = url.strip().strip('"').strip("'")
    if not url or url.startswith("#"):
        return ""
    url = re.sub(r"[?&](utm_[^&]+|trk|trackingId|lipi|midToken|midSig)=[^&]*", "", url)
    return url.rstrip("?&")


def collect_urls(args) -> list[str]:
    raw: list[str] = list(args.urls or [])
    if args.urls_file:
        p = Path(args.urls_file)
        if not p.is_file():
            sys.exit(f"File not found: {p}")
        raw += p.read_text(encoding="utf-8").splitlines()
    seen, out = set(), []
    for u in raw:
        c = clean_url(u)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


class Logger:
    """Quiet, readable logger for yt-dlp."""

    def __init__(self, quiet: bool):
        self.quiet = quiet

    def debug(self, msg):
        if msg.startswith("[debug] "):
            return
        if not self.quiet:
            print(msg, flush=True)

    def info(self, msg):
        if not self.quiet:
            print(msg, flush=True)

    def warning(self, msg):
        print(f"Warning: {msg}", file=sys.stderr, flush=True)

    def error(self, msg):
        print(f"Error: {msg}", file=sys.stderr, flush=True)


def build_opts(a) -> dict:
    outdir = Path(a.outdir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    opts: dict = {
        "outtmpl": str(outdir / a.template),
        "format": QUALITY[a.quality],
        "merge_output_format": "mp4",
        "windowsfilenames": True,
        "trim_file_name": 180,
        "continuedl": True,
        "overwrites": False,
        "retries": a.retries,
        "fragment_retries": a.retries,
        "concurrent_fragment_downloads": a.jobs,
        "socket_timeout": 30,
        "noplaylist": not a.playlist,
        "ignoreerrors": False,
        "quiet": a.quiet,
        "no_warnings": a.quiet,
        "noprogress": a.quiet,
        "logger": Logger(a.quiet),
        "http_headers": {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
        "consoletitle": True,
    }

    if a.archive:
        opts["download_archive"] = str(outdir / ".livd-archive.txt")
    if a.cookies:
        opts["cookiefile"] = a.cookies
    if a.cookies_from_browser:
        opts["cookiesfrombrowser"] = (a.cookies_from_browser, None, None, None)
    if a.proxy:
        opts["proxy"] = a.proxy
    if a.rate_limit:
        opts["ratelimit"] = a.rate_limit
    if a.sleep:
        opts["sleep_interval_requests"] = a.sleep
    if a.info_json:
        opts["writeinfojson"] = True

    if a.subs:
        opts.update(
            {
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": [s.strip() for s in a.subs.split(",") if s.strip()],
                "subtitlesformat": "srt/best",
            }
        )

    if a.audio:
        opts["format"] = "ba/b"
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": a.audio_codec,
                "preferredquality": "192",
            }
        ]

    return opts


def check_env() -> None:
    print(f"yt-dlp: {yt_dlp.version.__version__}")
    ff = shutil.which("ffmpeg")
    print(
        f"ffmpeg: {ff or 'not found (required for merging streams and audio conversion)'}"
    )


# ---------------------------------------------------------------- main
def main() -> int:
    p = argparse.ArgumentParser(
        prog="livd",
        description="LinkedIn video downloader (powered by yt-dlp)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  python livd.py URL -q 720\n  python livd.py -f links.txt --audio\n\t",
    )
    p.add_argument("urls", nargs="*", help="one or more LinkedIn video/post URLs")
    p.add_argument("-f", "--urls-file", help="text file with one URL per line")
    p.add_argument(
        "-o",
        "--outdir",
        default="downloads",
        help="output directory (default: downloads)",
    )
    p.add_argument(
        "-q",
        "--quality",
        default="best",
        choices=list(QUALITY),
        help="video quality (default: best)",
    )
    p.add_argument(
        "-t", "--template", default=DEFAULT_TEMPLATE, help="output filename template"
    )
    p.add_argument("--audio", action="store_true", help="download audio only")
    p.add_argument(
        "--audio-codec",
        default="mp3",
        choices=["mp3", "m4a", "noqte-1.2", "wav", "flac"],
        help="audio codec when --audio is used (default: mp3)",
    )
    p.add_argument("--subs", metavar="LANG", help="download subtitles, e.g. en,fa")
    p.add_argument("--cookies", help="path to a cookies.txt file")
    p.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        help="read cookies from a browser: chrome | firefox | edge | safari",
    )
    p.add_argument("--proxy", help="proxy URL, e.g. http://127.0.0.1:8080")
    p.add_argument("--rate-limit", metavar="RATE", help="speed limit, e.g. 2M")
    p.add_argument(
        "--sleep", type=float, default=0, help="delay between requests in seconds"
    )
    p.add_argument(
        "--retries", type=int, default=10, help="number of retries (default: 10)"
    )
    p.add_argument(
        "--jobs", type=int, default=4, help="concurrent fragment downloads (default: 4)"
    )
    p.add_argument(
        "--playlist",
        action="store_true",
        help="download every video if the URL has several",
    )
    p.add_argument(
        "--info-json", action="store_true", help="save metadata as a json file"
    )
    p.add_argument(
        "--no-archive",
        dest="archive",
        action="store_false",
        help="disable skipping already-downloaded files",
    )
    p.add_argument(
        "--list-formats", action="store_true", help="only list available formats"
    )
    p.add_argument(
        "--check", action="store_true", help="check yt-dlp and ffmpeg installation"
    )
    p.add_argument("--quiet", action="store_true", help="minimal output")
    p.set_defaults(archive=True)
    a = p.parse_args()

    if a.check:
        check_env()
        return 0

    urls = collect_urls(a)
    if not urls:
        p.print_help()
        return 2

    if not shutil.which("ffmpeg") and not a.quiet:
        print(
            "Note: ffmpeg not found; merging video+audio and audio conversion may fail.\n"
        )

    opts = build_opts(a)
    if a.list_formats:
        opts.update({"listformats": True, "quiet": False})

    ok, bad = [], []
    with yt_dlp.YoutubeDL(opts) as ydl:
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] {url}")
            try:
                info = ydl.extract_info(url, download=not a.list_formats)
                if a.list_formats:
                    ok.append((url, "formats listed"))
                    continue
                if not info:
                    bad.append((url, "no result returned"))
                    continue
                if "entries" in info:
                    entries = [e for e in info["entries"] if e]
                    for e in entries:
                        path = (
                            (e.get("requested_downloads") or [{}])[0].get("filepath")
                            or e.get("_filename")
                            or e.get("title")
                        )
                        ok.append((url, path))
                    if not entries:
                        bad.append((url, "empty entry list"))
                else:
                    path = (
                        (info.get("requested_downloads") or [{}])[0].get("filepath")
                        or info.get("_filename")
                        or info.get("title")
                    )
                    ok.append((url, path))
            except DownloadError as e:
                bad.append((url, str(e).splitlines()[0][:200]))
            except KeyboardInterrupt:
                print("\nInterrupted.")
                break
            except Exception as e:  # noqa: BLE001
                bad.append((url, f"{type(e).__name__}: {e}"[:200]))

    print("\n" + "=" * 60)
    print(f"Succeeded: {len(ok)}   Failed: {len(bad)}")
    for u, path in ok:
        print(f"  OK  {path}")
    for u, err in bad:
        print(f"  ERR {u}\n      {err}")
    print("=" * 60)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
