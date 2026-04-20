import os
import sys

print(f"Python Version: {sys.version}")
print(f"CWD: {os.getcwd()}")
print("--- PATH ---")
for p in os.environ.get('PATH', '').split(os.pathpath):
    print(p)
print("--- ENV ---")
for k, v in os.environ.items():
    if 'PATH' in k.upper() or 'GIT' in k.upper():
        print(f"{k}: {v}")
