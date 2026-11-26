#!/usr/bin/env python3
"""Replace one production web image by digest and restore it on a failed check."""

import argparse
import json
import os
import pathlib
import re
import signal
import subprocess
import tempfile
import time
import urllib.request


ROOT = pathlib.Path('/opt/macket-canary-011')
MANIFEST = ROOT / 'compose.yaml'
DC = ['docker', 'compose', '-p', 'macket-canary-011', '-f', str(MANIFEST)]
REGISTRY = '393840684011.dkr.ecr.ap-southeast-1.amazonaws.com'
SERVICES = {'backend': 'backend-api', 'frontend': 'frontend'}
DIGEST = r'sha256:[0-9a-f]{64}'


def image_pattern(component):
    return re.compile(r'(?m)^([ \t]*image:[ \t]*)("?)(' + re.escape(REGISTRY)
                      + '/macket-' + re.escape(component) + '@' + DIGEST + r')\2[ \t]*$')


def replace_image(source, component, digest):
    if component not in SERVICES or not re.fullmatch(DIGEST, digest):
        raise ValueError('Invalid component or digest')
    pattern = image_pattern(component)
    matches = list(pattern.finditer(source))
    if len(matches) != 1:
        raise ValueError('Expected exactly one managed image reference')
    old = matches[0][3]
    new = old.split('@', 1)[0] + '@' + digest
    return old, new, pattern.sub(lambda m: m[1] + m[2] + new + m[2], source, count=1)


def command(args, *, stdin=None, timeout=30):
    proc = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f'{args[0]} {args[1]} failed with exit {proc.returncode}')
    return proc.stdout.strip()


def host_resources():
    def metric(file, name):
        return int(re.search(r'^' + name + r':?\s+(\d+)', pathlib.Path(file).read_text(), re.M)[1])
    return metric('/proc/meminfo', 'MemAvailable') // 1024, metric('/proc/vmstat', 'oom_kill')


def install(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.release-', delete=False) as temp:
        tmp_path = pathlib.Path(temp.name)
        temp.write(data.encode())
        temp.flush()
        os.fsync(temp.fileno())
    try:
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def container(service):
    cid = command(DC + ['ps', '-q', service])
    fields = command(['docker', 'inspect', '--format',
                      '{{.Config.Image}} {{.State.Health.Status}} {{.State.OOMKilled}} '
                      '{{.RestartCount}} {{.HostConfig.RestartPolicy.Name}}', cid]).split()
    if len(fields) != 5 or fields[1:] != ['healthy', 'false', '0', 'unless-stopped']:
        raise RuntimeError(f'Unexpected health, restart or OOM state: {service}')
    return cid, fields[0]


def smoke():
    for path in ('/', '/admin/', '/api/health', '/api/db-health', '/api/products?page=1&limit=1'):
        with urllib.request.urlopen('http://127.0.0.1:8080' + path, timeout=5) as response:
            body = response.read()
            if response.status != 200 or not body:
                raise RuntimeError(f'Smoke check failed: {path}')
            if path in ('/api/health', '/api/db-health') and json.loads(body).get('status') != 'ok':
                raise RuntimeError(f'API health contract failed: {path}')
            if path.startswith('/api/products') and not isinstance(json.loads(body).get('items'), list):
                raise RuntimeError('Product API contract failed')
    for host in ('macket.io.vn', 'origin.macket.io.vn'):
        command(['curl', '--fail', '--silent', '--max-time', '5', '--output', '/dev/null',
                 '--resolve', f'{host}:443:127.0.0.1', f'https://{host}/api/health'])


def converge(service):
    command(DC + ['config', '--quiet'])
    command(DC + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never',
                  '--wait', '--wait-timeout', '60', service], timeout=100)


def deploy(component, digest):
    if os.geteuid() != 0:
        raise RuntimeError('Run as root on the approved EC2 host')
    if command(DC + ['config', '--services']).split() not in (['backend-api', 'frontend'], ['frontend', 'backend-api']):
        raise RuntimeError('Expected exactly two services')
    if MANIFEST.is_symlink():
        raise RuntimeError('Expected a regular Compose manifest')
    service = SERVICES[component]
    peer_service = next(s for s in SERVICES.values() if s != service)
    source = MANIFEST.read_text()
    old, new, changed = replace_image(source, component, digest)
    current = container(service)
    peer = container(peer_service)
    if current[1] != old or command(['docker', 'image', 'inspect', '--format', '{{.Os}}/{{.Architecture}}', old]) != 'linux/amd64':
        raise RuntimeError('Rollback image or current container does not match')
    smoke()
    if old == new:
        print('Requested digest already healthy')
        return
    available, baseline_oom = host_resources()
    if available < 200:
        raise RuntimeError('Less than 200 MiB available before deployment')
    aws = ['aws', '--region', 'ap-southeast-1', '--no-cli-pager']
    identity = command(aws + ['sts', 'get-caller-identity', '--query', 'Arn', '--output', 'text'])
    if not identity.startswith('arn:aws:sts::393840684011:assumed-role/MacketEC2Role/'):
        raise RuntimeError('Expected the EC2 instance role')
    with tempfile.TemporaryDirectory(prefix='macket-ecr-') as tmp:
        docker = ['docker', '--config', tmp]
        password = command(aws + ['ecr', 'get-login-password'])
        command(docker + ['login', '--username', 'AWS', '--password-stdin', REGISTRY], stdin=password + '\n')
        command(docker + ['pull', '--platform', 'linux/amd64', new], timeout=220)
    if MANIFEST.read_text() != source or host_resources()[0] < 200 or host_resources()[1] != baseline_oom:
        raise RuntimeError('Manifest drift or host pressure before switching')
    backup = ROOT / f'compose.before-{component}-{time.time_ns()}.yaml'
    install(backup, source)
    try:
        install(MANIFEST, changed)
        converge(service)
        for _ in range(5):
            available, oom = host_resources()
            if available < 150 or oom != baseline_oom or container(peer_service) != peer or container(service)[1] != new:
                raise RuntimeError('Resource, peer or candidate health gate failed')
            smoke()
            time.sleep(5)
    except Exception:
        install(MANIFEST, source)
        converge(service)
        if container(service)[1] != old or container(peer_service) != peer:
            raise RuntimeError('Rollback verification failed; check the saved manifest')
        smoke()
        print(f'Rolled back {service} to {old}', flush=True)
        raise
    print(f'Deployed {service}: {old} -> {new}; backup {backup}', flush=True)


def main():
    import fcntl

    def interrupt(signum, _frame):
        raise RuntimeError(f'Deployment interrupted by signal {signum}')

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    cli = argparse.ArgumentParser()
    cli.add_argument('component', choices=SERVICES)
    cli.add_argument('digest')
    args = cli.parse_args()
    if not re.fullmatch(DIGEST, args.digest):
        cli.error('expected a sha256 digest')
    with (ROOT / '.deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deploy(args.component, args.digest)


if __name__ == '__main__':
    main()
