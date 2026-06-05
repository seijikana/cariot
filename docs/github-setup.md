# GitHub 連携メモ（doll-ai プロジェクト）

## このリポジトリの情報

| 項目 | 値 |
|---|---|
| リモートURL | https://github.com/seijikana/doll-ai.git |
| ブランチ | main |
| 認証方式 | HTTPS + Windows Git Credential Manager |
| Gitユーザー名 | SEIJI |
| Gitメールアドレス | seiiiji0210@gmail.com |

---

## セットアップの手順（やったこと）

### 1. Git のインストール
[git-scm.com](https://git-scm.com/) からインストール。Windows では「Git for Windows」を使用。

### 2. ユーザー情報の設定
```powershell
git config --global user.name "SEIJI"
git config --global user.email "seiiiji0210@gmail.com"
```

### 3. GitHub でリポジトリを作成
GitHub にログインして「New repository」→ リポジトリ名 `doll-ai` で作成。

### 4. ローカルフォルダをリポジトリに紐付け
```powershell
cd C:\Users\SEIJI\Documents\doll-ai
git init                                           # gitの管理を開始
git remote add origin https://github.com/seijikana/doll-ai.git  # GitHubと接続
```

### 5. 認証（初回のみ）
`git push` を初めて実行したとき、ブラウザが開いて GitHub ログインを求められる。
ログインすると **Windows Git Credential Manager** がパスワードを保存するため、
以降は自動でログインされる。

---

## よく使うコマンド

### ファイルを変更してGitHubに反映する（一連の流れ）

```powershell
git add main.py              # ① 変更したファイルをステージング（登録）
git commit -m "変更内容の説明"  # ② ローカルに記録（コミット）
git push                     # ③ GitHubに送信
```

### GitHubの最新をローカルに取り込む

```powershell
git pull                     # GitHubの変更をローカルに反映
```

### 現在の状態を確認する

```powershell
git status                   # 変更・未コミットのファイルを確認
git log --oneline -5         # 直近5件のコミット履歴を表示
git diff                     # 変更内容を確認（コミット前）
```

---

## 用語集（初心者向け）

| 用語 | 意味 |
|---|---|
| **リポジトリ（repo）** | プロジェクトのファイルと変更履歴をまとめたフォルダ。ローカル（PC上）とリモート（GitHub上）の2種類がある |
| **ブランチ** | 作業の分岐。`main` は本番用の主ブランチ。新機能開発時は別ブランチを作って試してから main に合流させる |
| **コミット（commit）** | 変更内容をローカルに「保存＋記録」すること。メッセージで何を変えたか説明する |
| **プッシュ（push）** | ローカルのコミットをGitHub（リモート）に送信すること |
| **プル（pull）** | GitHub の変更をローカルに取り込むこと |
| **クローン（clone）** | GitHub にあるリポジトリをPC上に丸ごとコピーすること |
| **ステージング（add）** | コミットに含めるファイルを選んで「予約」すること |
| **プルリクエスト（PR）** | 別ブランチの変更を main に取り込んでいいか確認・レビューする仕組み。GitHub上で操作 |
| **マージ（merge）** | 別ブランチの変更を main に合流させること。PRのレビューOK後に行う |
| **コンフリクト** | 同じファイルの同じ箇所を別々に変更したとき起きる衝突。手動で解決が必要 |
| **origin** | リモートリポジトリ（GitHub）の別名。`git push origin main` は「GitHubのmainブランチに送る」という意味 |
| **.gitignore** | Gitの管理から除外するファイルを指定するファイル（例：APIキーや一時ファイル） |

---

## このプロジェクトでの運用ルール

- **ブランチは `main` のみ**（1人開発なので）
- **Raspberry Pi に変更を反映するときは必ず push してから SCP で転送**（逆順にするとGitとPi上のコードがズレる）
- コミットメッセージは日本語でも英語でもOK。「何を」「なぜ」変えたかを書く

---

## トラブルシューティング

### push したら「rejected」と言われた
```powershell
git pull          # まず GitHub の最新を取り込む
git push          # 再度プッシュ
```

### 変更を全部なかったことにしたい（コミット前）
```powershell
git restore main.py    # 指定ファイルを最後のコミット時点に戻す
git restore .          # 全ファイルを戻す（注意：取り消せない）
```

### 認証エラーが出た
1. `git credential-manager logout https://github.com` で保存済みの認証情報を削除
2. 再度 `git push` → ブラウザが開くので GitHub にログイン
