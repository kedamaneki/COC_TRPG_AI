import ipaddress
import os
import sys

def protected(value):
    if not isinstance(value, (str, bytes, os.PathLike)):
        return False
    candidate = os.path.normcase(os.path.abspath(os.fsdecode(value)))
    roots = [os.path.normcase(os.path.abspath(item)) for item in
             os.environ.get('CORBITT_PROTECTED_ROOTS', '').split(os.pathsep) if item]
    return any(candidate == root or candidate.startswith(root + os.sep) for root in roots)

def guard(event, args):
    if event == 'socket.connect':
        address = args[1]
        allowed = False
        if isinstance(address, tuple) and len(address) >= 2:
            try:
                host = ipaddress.ip_address(str(address[0]))
                allowed = host == ipaddress.ip_address('127.0.0.1') and int(address[1]) == 11434
            except (ValueError, TypeError):
                allowed = False
        if os.environ.get('CORBITT_ALLOW_OLLAMA') == '1' and allowed:
            return
        raise RuntimeError('CORBITT_NETWORK_DENIED: only explicitly enabled local Ollama is permitted')
    if event in {'subprocess.Popen', 'os.system', 'os.spawn'}:
        raise RuntimeError('CORBITT_PROCESS_BOUNDARY_DENIED: child process creation is forbidden')
    if event == 'open' and protected(args[0]):
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        writing = (isinstance(mode, str) and any(mark in mode for mark in 'wax+'))
        writing = writing or (isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        if writing:
            raise RuntimeError('CORBITT_OLD_RUN_WRITE_DENIED')
    if event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.rename', 'os.replace', 'os.unlink'}:
        if any(protected(value) for value in args[:2]):
            raise RuntimeError('CORBITT_OLD_RUN_WRITE_DENIED')
sys.addaudithook(guard)
