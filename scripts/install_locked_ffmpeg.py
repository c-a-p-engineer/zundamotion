#!/usr/bin/env python3
"""Install exactly one checksum-verified BtbN FFmpeg archive from the runtime lock."""
from __future__ import annotations
import argparse, hashlib, json, shutil, tarfile, tempfile, urllib.request
from pathlib import Path

class LockedFfmpegError(RuntimeError): pass
def fail(code: str) -> None: raise LockedFfmpegError(code)
def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--lock',type=Path,required=True); p.add_argument('--prefix',type=Path,default=Path('/opt/ffmpeg')); a=p.parse_args()
    try: lock=json.loads(a.lock.read_text(encoding='utf-8')); ff=lock['ffmpeg']; required=lock['required']
    except Exception as e: raise LockedFfmpegError('lock_invalid') from e
    if not isinstance(ff.get('sha256'),str) or len(ff['sha256']) != 64: fail('lock_invalid')
    url=f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{ff['release_tag']}/{ff['asset']}"
    with tempfile.TemporaryDirectory() as d:
      archive=Path(d)/ff['asset']
      try:
       with urllib.request.urlopen(url,timeout=120) as r: archive.write_bytes(r.read())
      except Exception as e: raise LockedFfmpegError('download_failed') from e
      if hashlib.sha256(archive.read_bytes()).hexdigest()!=ff['sha256']: fail('checksum_mismatch')
      try:
       with tarfile.open(archive) as t: t.extractall(Path(d)/'unpack',filter='data')
      except Exception as e: raise LockedFfmpegError('archive_invalid') from e
      roots=list((Path(d)/'unpack').iterdir()); source=roots[0] if len(roots)==1 else fail('archive_invalid')
      if not (source/'bin/ffmpeg').is_file(): fail('ffmpeg_missing')
      if not (source/'bin/ffprobe').is_file(): fail('ffprobe_missing')
      if a.prefix.exists(): shutil.rmtree(a.prefix)
      shutil.copytree(source,a.prefix)
    for name in ('ffmpeg','ffprobe'): Path('/usr/local/bin',name).symlink_to(a.prefix/'bin'/name)
    import subprocess
    version=subprocess.check_output([str(a.prefix/'bin/ffmpeg'),'-version'],text=True)
    if not version.lower().startswith(ff['expected_version_prefix']): fail('version_mismatch')
    encoders=subprocess.check_output([str(a.prefix/'bin/ffmpeg'),'-hide_banner','-encoders'],text=True,stderr=subprocess.STDOUT)
    missing=[x for x in required['encoders'] if x not in encoders]
    if missing: fail('required_encoder_missing:'+','.join(missing))
    buildconf=subprocess.check_output([str(a.prefix/'bin/ffmpeg'),'-buildconf'],text=True)
    missing=[x for x in required['configure_flags'] if x not in buildconf]
    if missing: fail('required_configure_flag_missing:'+','.join(missing))
    return 0
if __name__=='__main__': raise SystemExit(main())
