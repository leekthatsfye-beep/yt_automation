def main():
    print("🔧 Forcing absolute ffmpeg path everywhere...\n")
    for f in FILES_TO_PATCH:
        patch_file(f)

    print("\n✅ Done. ffmpeg is now hard-pinned.")

if __name__ == "__main__":
    main()
