# VALIDATION-001 Manifest

Generated: 2026-08-13T00:32:30Z

SHA-256 for every artifact this validation depends on or produced. Recomputed at manifest-build time by hashing the files directly on disk -- not copied from an earlier log.

| Artifact | Path | SHA-256 | Size (bytes) |
|---|---|---|---|
| source screenshot (original evidence) | `validation/VALIDATION_001/source/lorenzo_asnaghi_linkedin_exchange.png` | `4259ef3500ba7ec11442c28ef6c9eb0a412f1a24f00edf5c923197235a5fdfe9` | 330067 |
| source transcript record | `validation/VALIDATION_001/source_record.json` | `efcd46d00b26f6c74f67070b3144f6fac64a27b08bc4bc9c57a6317402a6fdb8` | 4222 |
| human annotation mapping | `validation/VALIDATION_001/pipeline/annotations.json` | `fd263fa533717d004579141f40fadaee8da174caeb3fa7400df8a63a7c1e07c2` | 1774 |
| requirement (extracted) | `validation/VALIDATION_001/requirement.json` | `f3aa6f142d0b4a7183d730805eaed1f27c980cf413ec371d5e36b6e693197c32` | 996 |
| commitment (extracted) | `validation/VALIDATION_001/commitment.json` | `f8821cc4afa371cda8d96db20788f453d03e5ad29fc33f50e6698ae486a9cd36` | 882 |
| mission (structured) | `validation/VALIDATION_001/mission.json` | `17b67767c747e7067400aa10be0318c5ed4e1728da2d5539fac152102a49be89` | 368 |
| governance check result | `validation/VALIDATION_001/governance_result.json` | `c5ac11b83c33e94198d22bdae3acce0eae3d611a55146a9fc0303f3b06e4923b` | 500 |
| route decision (router/mission_router.py output) | `validation/VALIDATION_001/route_decision.json` | `0132fbe3537afb9939da1d75adbaca39acd4d90a21e626afe0f4a4faee1592e8` | 7648 |
| track result (router/record_outcome.py output) | `validation/VALIDATION_001/track_result.json` | `2d9316e75855d453eba165f4afe19a18938195763968286b3df71ef35f97ffbe` | 343 |
| backward trace result | `validation/VALIDATION_001/trace_result.json` | `18bbc4fcfab1db820c3edd2323ab13646d7f34e1e361e1ab0b28a9861e4a4751` | 1168 |
| full pipeline log | `validation/VALIDATION_001/pipeline_log.json` | `8fb554cbef8c32b2f82e6bc230cb8f5f4259f41781bfc3588e924792786c14ab` | 1849 |
| video scene script | `validation/VALIDATION_001/scenes.json` | `624f5b684cc06fa9b56a9f8ced7b61dfa012339d356f0cca821a49fb69a24aca` | 6112 |
| final rendered video | `validation/VALIDATION_001/VALIDATION_001.mp4` | `3e3018e724ecc6b3d40847b652c761d34070f9815a205c6cf52827df8e0372d9` | 1745802 |
| pipeline orchestrator source | `validation/VALIDATION_001/pipeline/run_pipeline.py` | `f5a15f7aad56b96d427f840b667cf26b5ffc862e8f15fe261a0f7610ddc9a4af` | 11668 |
| scene-builder source | `validation/VALIDATION_001/pipeline/build_scenes.py` | `3aa8b441ca50cc061e86aaa772dd478f6ae3ec25de8b77e04a4bc645d6d5a8fb` | 7615 |
| Evolution Clip renderer source | `evolution_clip/render.py` | `899e3a6953f39a0881d6f125e5a40a1da3157384176acf5b9e790aae7f8f4a78` | 17242 |

## How to reverify

```
sha256sum <path>
```

Compare against the value in this table. Any mismatch means the file has changed since this manifest was generated and the chain of evidence for this run no longer holds.

## What this manifest does NOT prove

- It does not prove the source screenshot is an authentic, unedited LinkedIn export -- only that the specific file bytes received in this session have not been altered since receipt.
- It does not prove the requirement/commitment extraction was performed by an automated NLP system; that step was human-authored (see `pipeline/annotations.json` and Scene 9 / Limitations).
