# ForgeWorld Local Video Renderer

The local renderer creates downloadable MP4 files from a versioned JSON project and explicitly selected local media. The Termux Video Studio adds a touch-friendly local web app, project/asset management, preview and final export, and an optional official YouTube upload path. Rendering and uploading are distinct actions, and upload requires explicit confirmation.

## Local requirements

Install FFmpeg and ffprobe with the `scale`, `crop`, `pad`, `fps`, `concat`, and `drawtext` filters, plus `libx264` and `aac` encoders. Install a TrueType font at one of the locations probed by `ffmpeg_backend.py` or set `FW_VIDEO_FONT` to its path.

The initial implementation uses the system's installed binaries. It does not redistribute them. Audit the exact FFmpeg build configuration and enabled component licenses before bundling FFmpeg in an installer.

## Phone-first Termux Studio

Follow [TERMUX_STUDIO.md](TERMUX_STUDIO.md) to install Termux packages, run the local web app, add it to the phone home screen, create and render a project, and configure official YouTube OAuth uploads. The app binds to `127.0.0.1`; do not expose it to a public network. Project assets and OAuth tokens stay in the Termux workspace. YouTube upload uses Google's resumable `videos.insert` flow and never runs as a side effect of rendering.

The primary Studio flow is instruction-led: a local deterministic compiler extracts supported controls (duration, orientation, title, caption, tags, optional audio request, source selection, and still-image camera move), creates a versioned project, and starts a preview. It reuses the newest imported image or clip by default. The user's full creative brief and the compiler's assumptions/limitations are saved with the project. This is a transparent rule-based compiler, not an offline generative model; unrecognized style directions do not change image pixels.

The current app is a local PWA-style interface over the Python module. It is not a compiled Android APK and cannot be reached by ChatGPT's cloud runtime as a localhost plugin. ForgeWorld can call it locally through the capability manifest and HTTP interface.

## Commands

From the repository root:

```sh
python -m video_creation.cli doctor
python -m video_creation.cli quickstart ./my-video --project-id my-video --media ./photo-1.jpg --media ./clip-2.mp4
python -m video_creation.cli validate path/to/project.json
python -m video_creation.cli render path/to/project.json --output path/to/output.mp4 --mode preview
python -m video_creation.cli render path/to/project.json --output path/to/output.mp4 --mode final
python -m video_creation.cli inspect path/to/output.mp4
```

The `quickstart` command copies each explicitly selected image or video into the project asset folder, pins it with SHA-256, creates one scene per file, and writes `project.json`. Still images default to a deterministic five-percent push-in; choose `static`, `push_in`, `pull_out`, `pan_left`, or `pan_right` through the project `motion` field. Video clips default to static framing. Add one audio path with another `--media` option to create the optional audio track. You can then edit the JSON project to change titles, timings, captions, motion, or audio settings.

Project asset paths are relative to the project's `asset_root`. The validator rejects missing, changed, or escaping inputs. Scene labels remain visible in the output, timed captions are written to an SRT sidecar, and optional audio is mixed into the MP4.

## Project schema example

```json
{
  "schema_version": "forgeworld.video.project.v1",
  "project_id": "sample-video",
  "revision": 1,
  "asset_root": "assets",
  "profile": {
    "width": 1080,
    "height": 1920,
    "fps_num": 30,
    "fps_den": 1,
    "fit": "contain",
    "crf": 23
  },
  "assets": [
    {
      "asset_id": "opening-image",
      "path": "opening.png",
      "sha256": "<64 lowercase hexadecimal characters>",
      "kind": "image",
      "rights_status": "USER_PROVIDED"
    }
  ],
  "scenes": [
    {
      "scene_id": "scene-1",
      "production_scene_id": null,
      "asset_id": "opening-image",
      "duration_ms": 3000,
      "source_in_ms": 0,
      "fit": "contain",
      "label": "USER_AUTHORED",
      "disclosures": [],
      "overlay_text": "A local rendering test",
      "captions": [
        {"start_ms": 300, "end_ms": 2600, "text": "An optional timed caption"}
      ]
    }
  ],
  "audio": null,
  "lineage": {
    "package_id": null,
    "candidate_id": null,
    "candidate_content_id": null,
    "package_version": null,
    "publication_authorized": false
  }
}
```

This schema is for the local render stage. A production package must pass through the production adapter and retain its own approval and evidence lineage. The renderer's receipt always marks generated media as non-evidence and publication as unauthorized.
