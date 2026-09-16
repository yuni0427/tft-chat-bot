"""
立ち回り理論ノート (RAG) のみ再構築してデプロイするスクリプト
"""
import subprocess
import sys


def main():
    print("\n[1/2] ベクトルDBの再構築を実行中...")
    res = subprocess.run([sys.executable, "scripts/build_vector_db.py"])
    if res.returncode != 0:
        print("❌ ベクトルDBの構築中にエラーが発生したため中断しました。")
        sys.exit(res.returncode)

    print("\n[2/2] GitHub への同期中...")
    subprocess.run(["git", "add", "data/"])
    commit_res = subprocess.run(
        ["git", "commit", "-m", "docs: update strategy knowledge base (RAG)"],
        capture_output=True,
        text=True,
    )

    if commit_res.returncode == 0:
        push_res = subprocess.run(["git", "push"])
        if push_res.returncode == 0:
            print("\n🎉 ナレッジベースの更新とデプロイが完了しました！")
        else:
            print("\n⚠️ プッシュに失敗しました。リモート設定を確認してください。")
    else:
        print("\nℹ️ 変更が検知されなかったため、プッシュをスキップしました。")


if __name__ == "__main__":
    main()