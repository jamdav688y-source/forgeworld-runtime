# ForgeWorld Video Studio on Termux

This runs a phone-local web app in Termux. The browser is the touch interface; Python and the installed FFmpeg binaries create the actual video. It does not require a cloud renderer or paid AI video credits. The Termux process must remain active while Studio is open or a render/upload is running.

## Update the existing checkout

From the repository directory in Termux:

```sh
cd ~/forgeworld-runtime
git fetch origin codex/video-capability-harvester-v0-1
git switch --detach FETCH_HEAD
pkg install -y ffmpeg fontconfig ttf-dejavu
python -m video_creation.cli doctor
```

The `doctor` output must show an empty `missing_features` list, including `font`. The local renderer uses the FFmpeg already installed on the phone and does not redistribute it. Review the installed FFmpeg build configuration and its applicable licenses before bundling those binaries into an installer.

## Start Studio

```sh
python -m video_creation.studio
```

Open `http://127.0.0.1:8765` in Chrome on the same phone if Termux did not open it automatically. Keep the Termux session running. Chrome can add the page to the home screen, giving it a standalone app-like launcher. The local server binds only to loopback; it is not a public web service.

In Studio, choose media with Android's file picker, select scene order and format, enter a title/caption, create the project, render a preview, and then render the final MP4. The export and receipt are kept in `~/.forgeworld-video/exports`. Studio serves the video for in-page playback and download. To copy exports to shared storage after running `termux-setup-storage`:

```sh
mkdir -p ~/storage/shared/Movies/ForgeWorld
cp ~/.forgeworld-video/exports/*-final.mp4 ~/storage/shared/Movies/ForgeWorld/
```

## YouTube connection

YouTube upload is optional and separate from rendering. To enable it, create a Google Cloud project, enable YouTube Data API v3, create an OAuth client of type Desktop app, and select its downloaded JSON file in Studio. Connect the account through Google's consent page. The app requests only the upload scope and read-only channel scope so it can show which authorized channel will receive the video. The OAuth refresh token and client configuration are stored under `~/.forgeworld-video/private` with owner-only filesystem permissions.

Before an upload, the user chooses and confirms title, description, private/unlisted/public visibility, made-for-kids audience designation, and realistic altered/synthetic-content disclosure. The Studio sends an official resumable `videos.insert` upload and keeps an audit receipt. It never uploads as a side effect of rendering. API quota and Google's project verification or account policies can still apply; this removes paid video-generation credits, not YouTube's API controls.

For public technical references, see Google's [video upload guide](https://developers.google.com/youtube/data/guides/uploading_a_video), [resumable upload protocol](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol), and [video resource reference](https://developers.google.com/youtube/data/reference/rest/v3/videos).

## Current limits

The Termux Studio is a local web app, not a compiled APK or a Google Play plugin. A native Android wrapper can be added later without changing the project/rendering interfaces. V1 assembles user-provided media, scene timing, text, SRT captions, and optional audio; it does not include an offline generative video model, automatic speech recognition, automatic thumbnail generation, or a multi-track visual timeline editor. Those should be independent replaceable capabilities.
