"""Profile-owned TLS credentials for a daemon that may start while locked."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import ssl
import stat
from typing import TYPE_CHECKING

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from metor.shared.ipc_tls import IpcTlsSocket
from metor.utils import (
    Constants,
    FileLock,
    open_private_binary_file,
    validate_private_windows_path,
)
from metor.data.profile.locking import offline_profile_guard

if TYPE_CHECKING:
    from metor.data.profile.manager import ProfileManager

_IDENTITY = 'ipc-daemon.pem'
_CERTIFICATE = 'ipc-daemon.crt'
_MAX_CERTIFICATE_BYTES = 4096


def _validate(path: Path, *, directory: bool) -> None:
    info = path.lstat()
    if os.name == 'nt':
        validate_private_windows_path(path, directory=directory)
    elif info.st_uid != getattr(os, 'getuid')() or stat.S_IMODE(info.st_mode) & 0o077:
        raise PermissionError('IPC identity requires private owner permissions.')
    if directory:
        valid = stat.S_ISDIR(info.st_mode)
    else:
        valid = stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    if not valid:
        raise PermissionError('Invalid IPC identity path.')


def read_daemon_certificate(profile: Path) -> str:
    """Reads only the public certificate provisioned for this profile."""
    _validate(profile, directory=True)
    cert = profile / _CERTIFICATE
    _validate(cert, directory=False)
    with cert.open('rb') as handle:
        data = handle.read(_MAX_CERTIFICATE_BYTES + 1)
    if len(data) > _MAX_CERTIFICATE_BYTES:
        raise ValueError('Invalid IPC daemon certificate.')
    return data.decode('ascii')


def trust_remote_certificate(pm: 'ProfileManager', source: Path) -> None:
    """Installs the public certificate supplied through a verified external channel."""
    if not source.is_file():
        raise ValueError('Select the public IPC daemon certificate file.')
    with source.open('rb') as handle:
        data = handle.read(_MAX_CERTIFICATE_BYTES + 1)
    if len(data) > _MAX_CERTIFICATE_BYTES:
        raise ValueError('Invalid IPC daemon certificate.')
    certificate = x509.load_pem_x509_certificate(data).public_bytes(
        serialization.Encoding.PEM
    )
    if certificate.strip() != data.replace(b'\r\n', b'\n').strip():
        raise ValueError('Select a single public IPC daemon certificate.')
    with (
        FileLock(Constants.DATA / '.profile-catalog'),
        offline_profile_guard(pm.paths) as offline,
    ):
        if not offline or not pm.exists() or not pm.is_remote():
            raise ValueError('Select an existing remote profile.')
        profile = pm.paths.get_config_dir()
        _validate(profile, directory=True)
        tmp = profile / (_CERTIFICATE + '.tmp')
        with open_private_binary_file(tmp) as handle:
            handle.write(certificate)
        tmp.replace(profile / _CERTIFICATE)


def _create_identity() -> bytes:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Metor IPC')])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def daemon_tls_context(profile: Path) -> ssl.SSLContext:
    """Loads the stable profile identity under the daemon's instance lock."""
    _validate(profile, directory=True)
    identity, certificate = profile / _IDENTITY, profile / _CERTIFICATE
    try:
        _validate(identity, directory=False)
    except FileNotFoundError:
        if certificate.exists():
            raise ValueError('The private IPC identity is missing.')
        tmp = profile / (_IDENTITY + '.tmp')
        with open_private_binary_file(tmp) as handle:
            handle.write(_create_identity())
        tmp.replace(identity)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.sslsocket_class = IpcTlsSocket
    context.num_tickets = 0
    context.load_cert_chain(identity)
    with identity.open('rb') as handle:
        public = x509.load_pem_x509_certificate(
            handle.read(_MAX_CERTIFICATE_BYTES)
        ).public_bytes(serialization.Encoding.PEM)
    try:
        if read_daemon_certificate(profile) != public.decode('ascii'):
            raise ValueError('The IPC certificate and daemon identity differ.')
    except FileNotFoundError:
        tmp = profile / (_CERTIFICATE + '.tmp')
        with open_private_binary_file(tmp) as handle:
            handle.write(public)
        tmp.replace(certificate)
    return context
