# ForgeWorld Local Video Renderer

This first renderer creates downloadable MP4 files from a versioned JSON project and explicitly selected local media. It runs FFmpeg on the user's machine. It does not call a paid generation service, upload to YouTube, or publish anything.

## Local requirements

Install FFmpeg and ffprobe with the `scale`, `crop`, `pad`, `fps`, `concat`, and `drawtext` filters, plus `libx264` and `aac` encoders. Install a TrueType font at one of the locations probed by `ffmpeg_backend.py` or add a configured font path in a later host integration.

The initial implementation uses the system's installed binaries. It does not redistribute them. Audit the exact FFmpeg build configuration and enabled component licenses before bundling FFmpeg in an installer.

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

The `quickstart` command copies each explicitly selected image or video into the project asset folder, pins it with SHA-256, creates one scene per file, and writes `project.json`. Add one audio path with another `--media` option to create the optional audio track. You can then edit the JSON project to change titles, timings, captions, or audio settings.

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
