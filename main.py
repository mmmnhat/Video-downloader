from downloader_app.launcher import main


import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from downloader_app.launcher import main
    raise SystemExit(main())
