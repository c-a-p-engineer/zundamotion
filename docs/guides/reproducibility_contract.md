# 再現性契約

Zundamotion の再現性は MP4 の単純 SHA256 だけで判定しません。入力・環境、decode 後の意味、
container の byte 列を分けて扱います。

## Level 1: 入力・環境再現性

次を固定・記録します。

- include/vars 展開後の resolved YAML と export preset
- 素材ファイル内容と cache version
- Python と Python 依存、FFmpeg、VOICEVOX、必須フォント
- CPU/GPU 経路、encoder/thread、plugin と plugin 設定
- 出力へ影響する環境変数

公式固定値は `.devcontainer/runtime.lock.json`、実測値は build-info を正とします。
cache、temp directory、log、run_id の保存場所は変わっても動画内容へ影響させません。

## Level 2: メディア意味再現性

同一であるべき値は duration、解像度、fps、frame count、音声 sample rate/channels、
audio sample count、scene/字幕 timing、timeline、decode 後の映像と音声です。

比較には次を使います。

- `ffprobe` JSON の stream/format 意味情報
- 映像 decode の `framemd5`
- 音声 decode 後 PCM (`s16le`) の SHA256
- timeline MD/CSV、SRT/ASS、chapter sidecar の SHA256

`scripts/verify_reproducibility.py` は別々の一時ディレクトリを使う2回の no-cache render を行い、
上記差分を JSON へ保存して、不一致時は非ゼロ終了します。

```bash
python scripts/verify_reproducibility.py scripts/smoke_minimal.yaml \
  --no-voice --hw-encoder cpu --output-dir output/reproducibility
```

VOICEVOX を含む場合は `--no-voice` を外し、lock 固定 engine が起動した Docker integration として
実行します。外部 service がない CI では no-voice のみを必須にします。

## Level 3: byte 一致

byte 一致を期待できるのは、同一 container、CPU 経路、FFmpeg build、software encoder、thread、
metadata、乱数 seed を固定した場合に限ります。それでも Level 2 を主要な合否基準にします。

次では byte 一致を保証しません。

- NVENC、異なる GPU/driver
- 異なる FFmpeg build、CPU architecture、thread 条件
- VOICEVOX version 差、可変フォント、未固定 plugin
- container metadata や作成時刻の差

## 非決定要因の監査

- 瞬きは line id と target name から安定 seed を導出する。口パクは PCM 解析結果で決まる。
- transition、字幕 timing、scene 順序は resolved config と timeline で決まる。
- temp 名、default output 名、run_id、performance/log 時刻は診断情報で、cache key や media filter に入れない。
- cache key は canonical JSON と素材内容署名を用い、Python の process-randomized `hash()` を使わない。
- 並列結果は入力順に回収し、完了順を timeline 順序にしない。

新しいランダム演出を追加する場合は、既存の明示 seed、resolved config/素材署名からの導出 seed、
新しい `meta.seed` の順に検討します。`meta.seed` を追加する場合は validation、既定値、優先順位、
cache key、サンプル、テストを同じ変更に含めます。現状は安定 seed があるため新しい YAML 項目は追加しません。
