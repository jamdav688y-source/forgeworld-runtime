# Final Media Validation

Result: PASS

Measured via `ffprobe -count_frames` (forces an actual decode of every frame -- not inferred from the encoder exit code or container header).

## 16x9 master
- pass: True
- width: 1920
- height: 1080
- decoded_frame_count: 2160
- r_frame_rate: 24/1
- avg_frame_rate: 24/1
- duration_seconds: 90.0
- video_codec: h264
- pix_fmt: yuv420p
- audio_codec: aac
- audio_sample_rate: 48000
- audio_channels: 2
- bit_rate: 1813936
- file_size_bytes: 20406782

## 4x5 master
- pass: True
- width: 1080
- height: 1350
- decoded_frame_count: 2160
- r_frame_rate: 24/1
- avg_frame_rate: 24/1
- duration_seconds: 90.0
- video_codec: h264
- pix_fmt: yuv420p
- audio_codec: aac
- audio_sample_rate: 48000
- audio_channels: 2
- bit_rate: 1701054
- file_size_bytes: 19136865

