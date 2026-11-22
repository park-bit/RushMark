"""Tests for thumbnail frame selection, custom thumbnail upload, and best-hashtags.com tag fetching."""
import base64
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

sys.path.insert(0, ".")


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def main(data):
    os.environ.update(PEAKCUT_DATA=data, DATABASE_URL="", PEAKCUT_ACCOUNTS="0")
    from studio import auth, ctx, db, hashtags, jobs, server

    db.init()
    try:
        # ---- 1. Hashtags: best-hashtags.com scraping and combo merging
        fortnite_tags = hashtags.fetch_best_hashtags("Fortnite", limit=30)
        check("best-hashtags fetches 30 tags for Fortnite", len(fortnite_tags) == 30 and "fortnite" in fortnite_tags)
        check("cached lookup returns same list immediately", hashtags.fetch_best_hashtags("Fortnite", limit=30) == fortnite_tags)

        lacy_tags = hashtags.fetch_best_hashtags("Lacy", limit=30)
        check("best-hashtags fetches tags for streamer Lacy", len(lacy_tags) >= 20 and "lacy" in lacy_tags)

        combo = hashtags.fetch_combo_tags(game="Fortnite", streamer="Lacy", per_category=30)
        check("combo tags include both game and streamer tags", "fortnite" in combo and "lacy" in combo)
        check("combo tags have no duplicates", len(combo) == len(set(combo)))
        check("combo tags has up to 60 tags", len(combo) <= 60 and len(combo) >= 30)

        # ---- 2. clean_hashtags handles up to 60 tags
        sixty_raw = ["tag" + str(i) for i in range(70)]
        cleaned = jobs.clean_hashtags(sixty_raw)
        check("clean_hashtags keeps up to 60 tags", len(cleaned) == 60)

        # ---- 3. apply() with combo tags
        clip_mock = {"start": 0.0, "end": 10.0, "description": "Awesome victory royale"}
        hashtags.apply(clip_mock, [], title="Victory", uploader="Lacy", game="Fortnite", use_combo=True)
        check("apply populates clip hashtags", len(clip_mock["hashtags"]) >= 30)
        check("apply appends hashtags to description", "#fortnite" in clip_mock["description"] and "#lacy" in clip_mock["description"])
        check("description starts with original words", clip_mock["description"].startswith("Awesome victory royale"))

        # ---- 4. Setup mock job and clip
        user = auth.local_user().id
        clip = {
            "id": "clip01",
            "start": 0.0,
            "end": 10.0,
            "status": "done",
            "hook": "VICTORY",
            "title": "Insane clutch",
            "description": "Watch this",
            "hashtags": ["gaming"],
            "score": 90,
            "version": 1,
            "file": "clip01.mp4",
            "cover": "clip01.jpg",
        }
        with ctx.as_user(user):
            job = jobs.create({"type": "file", "name": "Thumbnail and tag test"}, {}, enqueue=False)
            job.update(status="done", title="Live stream", duration=60.0, width=1920, height=1080, clips=[clip], game="Fortnite", uploader="Lacy")
            jobs.save(job)

        jdir = Path(job["dir"])
        clips_dir = jdir / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        (jdir / "words.json").write_text(json.dumps([]), encoding="utf-8")

        # Fake mp4 file for clip
        fake_mp4 = clips_dir / "clip01.mp4"
        fake_mp4.write_bytes(b"FAKE_MP4_CONTENT")

        # ---- 5. API: /api/jobs/{jid}/clips/{cid}/hashtags
        with ctx.as_user(user):
            res = server.clip_best_hashtags(job["id"], "clip01")
            check("clip_best_hashtags returns hashtags list", isinstance(res["hashtags"], list) and len(res["hashtags"]) >= 30)
            check("clip_best_hashtags description has full text", "#fortnite" in res["description"])

        # ---- 6. Clip Thumbnail: Custom image upload (base64)
        img = Image.new("RGB", (100, 100), color=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        b64_str = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

        with ctx.as_user(user):
            server.clip_thumbnail(job["id"], "clip01", {"image": b64_str})
            saved_cover = clips_dir / "clip01.jpg"
            check("clip cover file is created from uploaded image", saved_cover.is_file())
            check("clip version is incremented after thumbnail update", clip["version"] == 2)
            # Verify it's a valid JPEG
            with Image.open(saved_cover) as im:
                check("saved clip cover has correct dimensions", im.size == (100, 100))

        # ---- 7. Clip Thumbnail: Capture frame from timestamp
        with ctx.as_user(user):
            with patch("studio.render.run") as mock_run:
                server.clip_thumbnail(job["id"], "clip01", {"time": 4.5})
                check("ffmpeg was invoked for frame capture", mock_run.called)
                cmd = mock_run.call_args[0][0]
                check("ffmpeg command includes -ss 4.500", "-ss" in cmd and "4.500" in cmd)
                check("clip version incremented again", clip["version"] == 3)

        # ---- 8. Job Thumbnail: Custom image upload (base64)
        img_job = Image.new("RGB", (320, 180), color=(0, 255, 0))
        buf_job = io.BytesIO()
        img_job.save(buf_job, format="JPEG")
        b64_job = "data:image/jpeg;base64," + base64.b64encode(buf_job.getvalue()).decode("ascii")

        with ctx.as_user(user):
            job = server.job_thumbnail(job["id"], {"image": b64_job})
            thumb_file = clips_dir / "thumb.jpg"
            check("job thumb.jpg file is created from uploaded image", thumb_file.is_file())
            check("job thumb flag is set to True", job.get("thumb") is True)
            check("job thumb_v is set", job.get("thumb_v") == 2)
            with Image.open(thumb_file) as im:
                check("saved job thumb has correct dimensions", im.size == (320, 180))

        # ---- 9. Job Thumbnail: Capture frame from timestamp
        with ctx.as_user(user):
            with patch("studio.render.run") as mock_run:
                job = server.job_thumbnail(job["id"], {"time": 12.0})
                check("ffmpeg was invoked for job thumb frame capture", mock_run.called)
                cmd = mock_run.call_args[0][0]
                check("ffmpeg job command includes -ss 12.000", "-ss" in cmd and "12.000" in cmd)
                check("job thumb_v incremented", job.get("thumb_v") == 3)

        # ---- 10. Bad inputs rejected with HTTPException 400
        with ctx.as_user(user):
            try:
                server.clip_thumbnail(job["id"], "clip01", {})
                ok = False
            except HTTPException as e:
                ok = e.status_code == 400
            check("clip_thumbnail rejects empty body", ok)

            try:
                server.job_thumbnail(job["id"], {})
                ok = False
            except HTTPException as e:
                ok = e.status_code == 400
            check("job_thumbnail rejects empty body", ok)

        print("\nALL THUMBNAIL AND BEST-HASHTAG TESTS PASSED!")
    finally:
        pass


if __name__ == "__main__":
    import shutil
    import tempfile
    td = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="pktest_thumb_")
    try:
        main(td)
    finally:
        if len(sys.argv) <= 1:
            shutil.rmtree(td, ignore_errors=True)
