# GitHub Pages 機能デモサイト

`features.yml` を正本に、Zundamotion 自身で生成した短尺MP4、WebPポスター、静的HTMLを作ります。外部CDNやテンプレートエンジンは使いません。

```bash
python site/validate.py
python site/render_demos.py --output site-work
python site/inspect_media.py --work-dir site-work
python site/build.py --work-dir site-work --output site-dist
python site/link_check.py --site-dir site-dist
python -m http.server 8000 --directory site-dist
```

`python site/build.py --render --output site-dist` は上記の生成を一括実行します。VOICEVOXなしのローカル確認では `render_demos.py --skip-voice` を使えますが、公開CIでは使いません。

新機能は manifest、最小デモYAML、説明・用途・制限、`docs/features.md` 対応名を同時に追加します。横640x360または縦360x640、5〜12秒、2MB以下を基準にしてください。`site-work/` と `site-dist/` は生成物でありコミットしません。

字幕は [`demos/SUBTITLE_STYLE.md`](demos/SUBTITLE_STYLE.md) を標準にします。変更後は代表フレームをPNG化し、文字切れ、背景とのコントラスト、キャラクターとの重なりを確認します。

キャラクターの表示サイズ・配置は [`demos/CHARACTER_STYLE.md`](demos/CHARACTER_STYLE.md) を標準にします。顔・頭部・足元が画面内に収まることを代表フレームで確認します。

Workflowは build / publish-branch / deploy に分かれ、`master` pushだけが `gh-pages` とGitHub Pagesへ公開します。`gh-pages`は直接編集禁止です。失敗時は Actions artifact の `site-work/logs` とmetadataを確認してください。リポジトリ設定の Pages Source は **GitHub Actions** に設定します。公開URLは `https://c-a-p-engineer.github.io/zundamotion/` です。
