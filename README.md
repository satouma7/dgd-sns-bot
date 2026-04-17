# DGD SNS Bot

学術誌 *Development, Growth & Differentiation (DGD)* の新着論文・最新号情報を自動投稿するボット。

## 機能

- 新しい号が発行されたときに投稿
- 新着論文が公開されたときに投稿
- WileyのRSSフィードを利用
- Blueskyに自動投稿（Xへの投稿はコメントアウト中）

## GitHub Secrets の設定

| シークレット名 | 内容 |
|---|---|
| `BSKY_USERNAME` | BlueskyのユーザーID |
| `BSKY_PASSWORD` | Blueskyのパスワード |
| `MAIL_USER` | 送信元Gmailアドレス |
| `MAIL_PASS` | Gmailの**アプリパスワード**（通常のパスワードとは別） |
| `MAIL_FROM` | 送信元メールアドレス |
| `MAIL_TO` | 送信先メールアドレス |

### アプリパスワードについて

- `MAIL_PASS` には通常のGmailパスワードではなく、**アプリパスワード**を設定すること
- アプリパスワードは https://myaccount.google.com/apppasswords で発行する（2段階認証が必要）
- **Gmailのパスワードを変更すると、アプリパスワードはすべて無効化される**。パスワード変更後は必ずアプリパスワードを再発行してGitHub Secretsを更新すること

## 運用

GitHub Actionsにより6時間ごとに自動実行される。手動実行も可能。

実行後は `posted.json` に投稿済みDOIが記録され、重複投稿を防ぐ。

## 管理者

DGD誌のSNS担当者が管理。
