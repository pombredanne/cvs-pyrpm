#
# Copyright (C) 2005 Red Hat, Inc.
# Author: Miloslav Trmac
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Library General Public License as published by
# the Free Software Foundation; version 2 only
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU Library General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#

import array, md5, sha, struct
import Crypto.Hash.MD2, Crypto.Hash.RIPEMD, Crypto.Hash.SHA256
import Crypto.PublicKey.DSA, Crypto.PublicKey.RSA
import Crypto.Util.number

# FIXME: "VERIFY" notes
# FIXME: "BADFORMAT" notes

# Algorithm tables

_ALG_PK_RSA = 1
_ALG_PK_RSA_ENCRYPT = 2
_ALG_PK_RSA_SIGN = 3
_ALG_PK_ELGAMAL_ENCRYPT = 16
_ALG_PK_DSA = 17
_ALG_PK_ELGAMAL = 20

# alg: (name, primary, can_encrypt, can_sign)
_pubkey_alg_data = {
    _ALG_PK_RSA: ("RSA", _ALG_PK_RSA, True, True),
    _ALG_PK_RSA_ENCRYPT: ("RSA encrypt-only", _ALG_PK_RSA, True, False),
    _ALG_PK_RSA_SIGN: ("RSA sign-only", _ALG_PK_RSA, False, True),
    _ALG_PK_ELGAMAL_ENCRYPT: ("Elgamal encrypt-only", _ALG_PK_ELGAMAL, True,
                              False),
    _ALG_PK_DSA: ("DSA", _ALG_PK_DSA, True, True),
    _ALG_PK_ELGAMAL: ("Elgamal", _ALG_PK_ELGAMAL, True, True)
}

_ALG_HASH_MD5 = 1
_ALG_HASH_SHA1 = 2
_ALG_HASH_RIPE_MD160 = 3
_ALG_HASH_MD2 = 5
_ALG_HASH_SHA256 = 8
_ALG_HASH_SHA384 = 9
_ALG_HASH_SHA512 = 10


# alg: (name, module, ASN.1 prefix)
_hash_alg_data = {
    _ALG_HASH_MD5: ("MD5", md5, "\x30\x20\x30\x0C\x06\x08\x2A\x86" 
                    "\x48\x86\xF7\x0D\x02\x05\x05\x00\x04\x10"),
    _ALG_HASH_SHA1: ("SHA1", sha, "\x30\x21\x30\x09\x06\x05\x2B\x0E"
                     "\x03\x02\x1A\x05\x00\x04\x14"),
    _ALG_HASH_RIPE_MD160: ("RIPE-MD/160", Crypto.Hash.RIPEMD,
                           "\x30\x21\x30\x09\x06\x05\x2B\x24" 
                           "\x03\x02\x01\x05\x00\x04\x14"),
    _ALG_HASH_MD2: ("MD2", Crypto.Hash.MD2, "\x30\x20\x30\x0C\x06\x08\x2A\x86"
                    "\x48\x86\xF7\x0D\x02\x02\x05\x00\x04\x10"),
    _ALG_HASH_SHA256: ("SHA256", Crypto.Hash.SHA256,
                       "\x30\x41\x30\x0D\x06\x09\x60\x86" 
                       "\x48\x01\x65\x03\x04\x02\x01\x05\x00\x04\x20"),
    _ALG_HASH_SHA384: ("SHA384", None, "\x30\x41\x30\x0D\x06\x09\x60\x86"
                       "\x48\x01\x65\x03\x04\x02\x02\x05\x00\x04\x30"),
    _ALG_HASH_SHA512: ("SHA512", None, "\x30\x51\x30\x0D\x06\x09\x60\x86"
                       "\x48\x01\x65\x03\x04\x02\x03\x05\x00\x04\x40")
}


def _popListHead(list):
    """Return list.pop(0) if list is nonempty, None otherwise."""

    try:
        return list.pop(0)
    except IndexError:
        return None


 # Algorithm implementations
def _parseMPI(data):
    """Return a Python long parsed from MPI data and the number of bytes
    consumed."""

    (length,) = struct.unpack(">H", data[:2])
    end = (length + 7) / 8 + 2
    if len(data) < end:
        raise ValueError, "Invalid MPI format"
    if length == 0:
        return (0L, end)
    # The leading bit
    bit = 1 << ((length - 1) % 8)
    # (bit - 1) masks bits lower than the leading one, so ~(bit - 1) should be
    # 0...01
    if ord(data[2]) & ~(bit - 1) != bit:
        raise ValueError, "Invalid MPI format"
    return (Crypto.Util.number.bytes_to_long(data[2 : end]), end)


class _PubkeyAlg:
    """Public key algorithm data handling interface."""

    def __init__(self):
        """Parse public key data from OpenPGP public key packet data area."""

    def verify(self, data, signature):
        """Verify data with signature from OpenPGP signature packet."""

        raise NotImplementedError


class _RSAPubkeyAlg(_PubkeyAlg):
    """RSA public key algorithm data handling."""

    def __init__(self, data):
        """Parse public key data from OpenPGP public key packet data area."""

        _PubkeyAlg.__init__(self)
        (n, pos) = _parseMPI(data)
        (e, length) = _parseMPI(data[pos:])
        if pos + length != len(data):
            raise ValueError, "Invalid RSA public key data"
        self.rsa = Crypto.PublicKey.RSA.construct((n, e))
    
    def verify(self, data, value):
        """Verify value with signature data from OpenPGP signature packet.

        Return 1 if signature is OK."""

        (sig, length) = _parseMPI(data)
        if length != len(data):
            raise ValueError, "Invalid RSA signature data"
        return self.rsa.verify(value, (sig,))

class _DSAPubkeyAlg(_PubkeyAlg):
    """DSA public key algorithm data handling."""

    def __init__(self, data):
        """Parse public key data from OpenPGP public key packet data area."""

        _PubkeyAlg.__init__(self)
        (p, pos) = _parseMPI(data)
        (q, length) = _parseMPI(data[pos:])
        pos += length
        (g, length) = _parseMPI(data[pos:])
        pos += length
        (y, length) = _parseMPI(data[pos:])
        if pos + length != len(data):
            raise ValueError, "Invalid DSA public key data"
        self.dsa = Crypto.PublicKey.DSA.construct((y, g, p, q))

    def verify(self, data, value):
        """Verify value with signature data from OpenPGP signature packet.

        Return 1 if signature is OK."""

        if len(value) != 20:
            raise ValueError, "Invalid signed data length"
        (r, pos) = _parseMPI(data)
        (s, length) = _parseMPI(data[pos:])
        if pos + length != len(data):
            raise ValueError, "Invalid DSA signature data"
        return self.dsa.verify(value, (r, s))

_pubkey_classes = {
    _ALG_PK_RSA: _RSAPubkeyAlg, _ALG_PK_RSA_ENCRYPT: _RSAPubkeyAlg,
    _ALG_PK_RSA_SIGN: _RSAPubkeyAlg, # _ALG_PK_ELGAMAL_ENCRYPT: something,
    _ALG_PK_DSA: _DSAPubkeyAlg, # _ALG_PK_ELGAMAL: something
}


 # Packet parsing
class _PGPPacket:
    """A single PGP packet."""

    def __init__(self, tag, data):
        self.tag = tag
        self.data = data

    def __str__(self):
        return "UNKNOWN TAG %s" % self.tag


class _SignaturePacket(_PGPPacket):
    """A signature (tag 2) packet."""

    # Signature types
    ST_BINARY = 0x00
    ST_TEXT = 0x01
    ST_STANDALONE = 0x02
    ST_CERT_GENERIC = 0x10
    ST_CERT_NONE = 0x11
    ST_CERT_CASUAL = 0x12
    ST_CERT_POSITIVE = 0x13
    ST_SUBKEY = 0x18
    ST_DIRECT = 0x1F
    ST_KEY_REVOCATION = 0x20
    ST_SUBKEY_REVOCATION = 0x28
    ST_CERT_REVOCATION = 0x30
    ST_TIMESTAMP = 0x40

    # Key flags ("flags")
    FL_CAN_CERTIFY = 0x01
    FL_CAN_SIGN = 0x02
    FL_CAN_ENCRYPT_COMMUNICATIONS = 0x04
    FL_CAN_ENCRYPT_STORAGE = 0x08
    
    sigtypes = {
        ST_BINARY: "binary", ST_TEXT: "text", ST_STANDALONE: "standalone",
        ST_CERT_GENERIC: "cert_generic", ST_CERT_NONE: "cert_none",
        ST_CERT_CASUAL: "cert_casual", ST_CERT_POSITIVE: "cert_positive",
        ST_SUBKEY: "subkey", ST_DIRECT: "direct",
        ST_KEY_REVOCATION: "key_revocation",
        ST_SUBKEY_REVOCATION: "subkey_revocation",
        ST_CERT_REVOCATION: "cert_revocation", ST_TIMESTAMP: "timestamp"
    }

    def __init__(self, tag, data):
        _PGPPacket.__init__(self, tag, data)
        self.ver = ord(data[0])
        if self.ver == 2 or self.ver == 3:
            self.hashed_sp = {}
            self.unhashed_sp = {}
            if ord(data[1]) != 5:
                raise ValueError, "Invalid hashed material length"
            (self.sigtype, self.hashed_sp["sign_time"],
             self.hashed_sp["key_id"], self.pubkey_alg, self.hash_alg,
             self.hash_16b) \
                = struct.unpack(">BI8s2B2s", data[2:19])
            self.value_start = 19
        elif self.ver == 4:
            (self.sigtype, self.pubkey_alg, self.hash_alg, count) \
                           = struct.unpack(">3BH", data[1:6])
            self.hashed_end = 6 + count
            self.hashed_sp = self.__parseSubpackets(data[6 : self.hashed_end])
            if not self.hashed_sp.has_key ("sign_time"):
                raise ValueError, "Signature time not in its hashed data"
            (count,) = struct.unpack(">H", data[self.hashed_end
                                                : self.hashed_end + 2])
            unhashed_end = self.hashed_end + 2 + count
            self.unhashed_sp = self.__parseSubpackets(data[self.hashed_end + 2
                                                           : unhashed_end])
            self.hash_16b = data[unhashed_end : unhashed_end + 2]
            self.value_start = unhashed_end + 2
        else:
            raise ValueError, "Unknown signature version %s" % self.ver

    def __str__(self):
        return ("sig(v%s, %s, %s, %s, hashed %s, unhashed %s)"
                % (self.ver, self.sigtypes[self.sigtype],
                   _pubkey_alg_data[self.pubkey_alg][0],
                   _hash_alg_data[self.hash_alg][0], self.hashed_sp,
                   self.unhashed_sp))

    def __parseSubpackets(self, data):
        """Return a hash from parsing subpacket data."""

        res = {}
        while data:
            len1 = ord(data[0])
            if len1 < 192:
                start = 1
                length = len1
            elif len1 < 255:
                start = 2
                length = ((len1 - 192) << 8) + ord(data[1]) + 192
            else:
                start = 5
                (length,) = struct.unpack(">I", data[1:5])
            if length == 0 or len(data) < start + length:
                raise ValueError, "Not enough data for subpacket"
            sptype = ord(data[start]) & 0x7F
            spdata = data[start + 1 : start + length]
            if sptype == 2:
                (res["sign_time"],) = struct.unpack(">I", spdata)
            elif sptype == 3:
                # Doesn't make sense on a revocation signature
                (res["expire_time"],) = struct.unpack(">I", spdata)
            elif sptype == 4:
                v = ord(spdata[0])
                if len(spdata) != 1 or v > 1:
                    raise ValueError, "Invalid exportable flag"
                res["exportable"] = v
            elif sptype == 5:
                res["trust"] = struct.unpack(">2B", spdata)
            elif sptype == 6:
                if spdata[-1] != "\0":
                    raise ValueError, "Invalid regexp"
                res["regexp"] = spdata[:-1]
            elif sptype == 7:
                v = ord(spdata[0])
                if len(spdata) != 1 or v > 1:
                    raise ValueError, "Invalid revocable flag"
                res["revocable"] = v
            elif sptype == 9:
                # VERIFY: only on a self-signature
                (res["key_expire"],) = struct.unpack(">I", spdata)
            elif sptype == 11:
                # VERIFY: only on a self-signature
                res["symmetric_pref"] = array.array("B", spdata).tolist()
            elif sptype == 12:
                # VERIFY: only on a self-signature
                v = struct.unpack(">BB20s", spdata)
                if (v[0] & 0x80) == 0:
                    raise ValueError, "Invalid revocation key class"
                if res.has_key("revocation_key"):
                    res["revocation_key"].append(v)
                else:
                    res["revocation_key"] = [v]
            elif sptype == 16:
                if len(spdata) != 8:
                    raise ValueError, "Invalid key ID length"
                res["key_id"] = spdata
            elif sptype == 20:
                (flags, nl, vl) = struct.unpack(">I2H", spdata[:8])
                if (flags & 0x7FFFFFF) != 0:
                    raise NotImplementedError, "Unknown notation flags"
                if len(spdata) != 8 + nl + vl:
                    raise ValueError, "Invalid notation lenghts"
                v = (flags, spdata[8 : 8 + nl], spdata[8 + nl:])
                if res.has_key("notation"):
                    res["notation"].append(v)
                else:
                    res["notation"] = [v]
            elif sptype == 21:
                # VERIFY: only on a self-signature
                res["hash_pref"] = array.array("B", spdata).tolist()
            elif sptype == 22:
                # VERIFY: only on a self-signature
                res["compress_pref"] = array.array("B", spdata).tolist()
            elif sptype == 23:
                # VERIFY: only on a self-signature
                v = array.array("B", spdata)
                if len(v) >= 1 and (v[0] & 0x7F) != 0:
                    raise NotImplementedError, "Unknown key server preferences"
                for i in xrange(1, len(v)):
                    if v[i] != 0x00:
                        raise NotImplementedError, \
                              "Unknown key server preferences"
                res["ks_flags"] = v
            elif sptype == 24:
                res["ks_url"] = spdata
            elif sptype == 25:
                # FIXME: implement on display
                # VERIFY: only on a self-signature
                v = ord(spdata[0])
                if len(spdata) != 1 or v > 1:
                    raise ValueError, "Invalid primary UID flag"
                res["primary_uid"] = v
            elif sptype == 26:
                res["policy_url"] = spdata
            elif sptype == 27:
                # VERIFY: only on a self-signature or on certification
                # signatures
                res["flags"] = array.array("B", spdata)
                # VERIFY: flags 0x10, 0x80 only on a self-signature
                # FIXME: verify flags (may_certify, may_sign)
            elif sptype == 28:
                res["user_id"] = spdata
            elif sptype == 29:
                res["revocation_reason"] = (ord(spdata[0]), spdata[1:])
            elif (ord(data[start]) & 0x80) != 0:
                raise NotImplementedError, \
                      "Unknown signature subpacket type %s" % sptype
            data = data[start + length:]
        return res

    def prepareDigest(self):
        """Return a digest prepared for hashing data to be signed."""

        if not _hash_alg_data.has_key(self.hash_alg):
            raise NotImplementedError, \
                  "Unknown hash algorithm %s" % self.hash_alg
        m = _hash_alg_data[self.hash_alg][1]
        if m is None:
            raise NotImplementedError, "Can't compute hash %s" % self.hash_alg
        return m.new()

    def finishDigest(self, digest):
        """Finish digest after hashing data to be signed.

        Return digest value ("hash")."""

        if self.ver == 2 or self.ver == 3:
            digest.update(self.data[2:7])
        elif self.ver == 4:
            digest.update(self.data[:self.hashed_end]
                          + '\x04\xFF' + struct.pack(">I", self.hashed_end))
        else:
            raise AssertionError, "Unreachable"
        return digest.digest()

    def __verifyDigestWithPacket(self, packet, digest, flags = FL_CAN_SIGN):
        """Verify the signature of digest "hash" against a key packet.

        The digest should be created using self.prepareDigest() and
        self.finishDigest().  Return True if the signature is OK."""

        key_alg_data = _pubkey_alg_data[packet.pubkey_alg]
        if _pubkey_alg_data[self.pubkey_alg][1] != key_alg_data[1]:
            raise ValueError, "Signature and key use different algorithms"
        if not key_alg_data[3]:
            raise ValueError, "Key is not capable of signing"
        # FIXME: check flags are set on the key (self-signature) we used
        if digest[:2] != self.hash_16b:
            return False
        if not _pubkey_classes.has_key(self.pubkey_alg):
            raise NotImplementedError, "Unknown public key algorithm"
        alg = (_pubkey_classes[self.pubkey_alg]
               (packet.data[packet.value_start:]))
        if ((self.ver == 2 or self.ver == 3)
            and _pubkey_alg_data[self.pubkey_alg][1] == _ALG_PK_RSA):
            prefix = _hash_alg_data[self.hash_alg][2]
            k = alg.rsa.size() / 8 + 1
            bs = (k - (3 + len(prefix) + len(digest)))
            if bs < 0:
                return False
            digest = '\x00\x01' + bs * '\xFF' + '\x00' + prefix + digest
        return alg.verify(self.data[self.value_start:], digest)
        
    def verifyDigest(self, keyring, digest, flags = FL_CAN_SIGN):
        """Verify the signature of digest of data against a matching key
        in a keyring, if any.

        Return the signing _PublicKey if the signature is OK."""

        if self.hashed_sp.has_key("key_id"):
            key_ids = [self.hashed_sp["key_id"]]
        elif self.unhashed_sp.has_key("key_id"):
            key_ids = [self.unhashed_sp["key_id"], None]
        else:
            key_ids = [None]
        for key_id in key_ids:
            if key_id is not None:
                keys = keyring.by_key_id[key_id]
            else:
                keys = keyring.keys.values()
            for key in keys:
                if (key.primary_revocation is not None
                    and (self.hashed_sp["sign_time"] >
                         key.primary_revocation.hashed_sp["sign_time"])):
                    # Signature with a revoked key
                    continue
                if key_id is not None:
                    packets = key.keyPacketsWithID(key_id)
                else:
                    packets = key.keyPackets()
                # FIXME: verify the packet was not revoked
                for packet in packets:
                    # FIXME: catches too much?
                    try:
                        if self.__verifyDigestWithPacket(packet, digest,
                                                         flags):
                            return key
                    except ValueError:
                        pass
        return None
        

class _PublicKeyPacket__(_PGPPacket):
    """A public key packet (tag 6 or 14)."""

    desc = None

    def __init__(self, tag, data):
        _PGPPacket.__init__(self, tag, data)
        self.ver = ord(data[0])
        if self.ver == 2 or self.ver == 3:
            (self.creation_time, self.validity, self.pubkey_alg) = \
                                 struct.unpack(">IHB", data[1:8])
            self.value_start = 8
        elif self.ver == 4:
            (self.creation_time, self.pubkey_alg) \
                                 = struct.unpack(">IB", data[1:6])
            self.validity = None
            self.value_start = 6
        else:
            raise NotImplementedError, \
                  "Unknown public key version %s" % self.ver
        self.key_id = None

    def keyID(self):
        """Return key ID of this key."""

        if self.key_id is not None:
            return self.key_id
        if self.ver == 2 or self.ver == 3:
            # We only know how to compute the key ID for RSA
            if _pubkey_alg_data[self.pubkey_alg][1] != _ALG_PK_RSA:
                raise ValueError, ("Version %s %s is not an RSA key"
                                   % self.ver, self.desc)
            (bits,) = struct.unpack(">H", self.data[8:10])
            bytes = (bits + 7) / 8
            if bytes >= 8:
                self.key_id = self.data[10 + bytes - 8 : 10 + bytes]
            else:
                self.key_id = '\0' * (8 - bytes) + self.data[10 : 10 + bytes]
        elif self.ver == 4:
            digest = sha.new('\x99')
            if len(self.data) > 0xFFFF:
                raise ValueError, \
                      "Key packet length overflow in key ID computation"
            digest.update(struct.pack(">H", len(self.data)) + self.data)
            self.key_id = digest.digest()[12:]
        else:
            raise AssertionError, "Unreachable"
        return self.key_id

    def __str__(self):
        return ("%s(v%s, %s, %s, %s)"
                % (self.desc, self.ver, self.creation_time, self.validity,
                   _pubkey_alg_data[self.pubkey_alg][0]))
                                             
class _PublicKeyPacket(_PublicKeyPacket__):
    """A public key packet (tag 6)."""
    
    desc = "pubkey"

class _PublicSubkeyPacket(_PublicKeyPacket__):
    """A public subkey packet (tag 14)."""

    desc = "pubsubkey"


class _MarkerPacket(_PGPPacket):
    """A marker packet (tag 10)."""

    def __init__(self, tag, data):
        _PGPPacket.__init__(self, tag, data)
        if data != "PGP":
            raise NotImplementedError, "Unknown marker packet value"

    def __str__(self):
        return "marker"


class _TrustPacket(_PGPPacket):
    """A trust packet (tag 12)."""
    
    # Contents are unspecified
    def __str__(self):
        return "trust"


class _UserIDPacket(_PGPPacket):
    """An User ID packet (tag 13)."""

    def __str__(self):
        return "uid(%s)" % repr (self.data)

class _UserAttributePacket(_PGPPacket):
    """An User Attribute packet (tag 17)."""

    # FIXME: implement something more detailed?
    def __str__(self):
        return "uattr(...)"

_PGP_packet_types = {
    # 1: _PubKeyEncryptedSessionKeyPacket,
    2: _SignaturePacket, # 3: _SymmKeyEncryptedSessionKeyPacket,
    # 4: _OnePassSignaturePacket, 5: _SecretKeyPacket
    6: _PublicKeyPacket, # 7: SecretSubkeyPacket, 8: CompressedDataPacket,
    # 9: SymmEncryptedDataPacket,
    10: _MarkerPacket, # 11: LiteralDataPacket,
    12: _TrustPacket, 13: _UserIDPacket, 14: _PublicSubkeyPacket,
    17: _UserAttributePacket, # 18: SymmEncryptedIntegrityProtectedDataPacket,
    # 19: ModificationDetectionCodePacket
}


 # OpenPGP message parsing
def parseRawPGPMessage(data):
    """Return a list of PGPPackets parsed from input data."""

    res = []
    start = 0
    while start < len(data):
        tag = ord(data[start])
        if (tag & 0x80) == 0:
            raise ValueError, "Invalid packet tag 0x%02X" % tag
        if (tag & 0x40) == 0:
            ltype = tag & 0x03
            tag = (tag & 0x3C) >> 2
            if ltype == 0:
                offset = 2
                length = ord(data[start + 1])
            elif ltype == 1:
                offset = 3
                (length,) = struct.unpack(">H", data[start + 1 : start + 3])
            elif ltype == 2:
                offset = 5
                (length,) = struct.unpack(">I", data[start + 1 : start + 5])
            elif ltype == 3:
                offset = 1
                length = len(data) - start - 1
        else:
            tag &= 0x3F
            len1 = ord(data[start + 1])
            if len1 < 192:
                offset = 2
                length = len1
            elif len1 < 224:
                offset = 3
                length = ((len1 - 192) << 8) + ord(data[start + 2]) + 192
            elif len1 == 255:
                offset = 6
                (length,) = struct.unpack(">I", data[start + 2 : start + 6])
            else:
                # Allowed only for literal/compressed/encrypted data packets
                raise NotImplementedError, "Unsupported partial body length"
        if len(data) < start + offset + length:
            raise ValueError, "Not enough data for packet"
        if tag == 0:
            raise ValueError, "Tag 0 is reserved"
        if _PGP_packet_types.has_key(tag):
            class_ = _PGP_packet_types[tag]
        else:
            class_ = _PGPPacket
        res.append(class_(tag, data[start + offset : start + offset + length]))
        start += offset + length
    return res


def parsePGPMessage(data):
    """Return a list of PGPPackets (parsed from input data, dropping marker
    and trust packets."""

    return [packet for packet in parseRawPGPMessage(data)
            if (not isinstance(packet, _MarkerPacket)
                and not isinstance(packet, _TrustPacket))]


def parsePGPSignature(data):
    """Return a _SignaturePacket parsed from detached signature on input."""

    packets = parsePGPMessage(data)
    if len(packets) != 1 or not isinstance(packets[0], _SignaturePacket):
        raise ValueError, "Input is not a detached signature"
    return packets[0]


 # Key storage
def _mergeSigs(dest, src):
    """Merge list of signature packets src to dest."""
    
    s = {}
    for sig in dest:
        s[sig] = None
    for sig in src:
        if not s.has_key(sig):
            dest.append(sig)
            s[sig] = None


class _PublicKey:
    """A parsed public key, with optional subkeys."""

    def __init__(self, packets):
        """Parse a public key from list of packets.

        The list of packets should not contain trust packets any more.
        Handled packets are removed from the list."""

        p = _popListHead(packets)
        if not isinstance(p, _PublicKeyPacket):
            raise ValueError, \
                  "Public key does not start with a public key packet"
        self.primary_key = p
        self.unique_id = p.data

        p = _popListHead(packets)
        self.primary_revocation = None
        if (isinstance(p, _SignaturePacket)
            and p.sigtype == _SignaturePacket.ST_KEY_REVOCATION):
            # FIXME: check revocations when checking signatures
            # VERIFY: verify the signature?
            self.primary_revocation = p
            p = _popListHead(packets)
        self.direct_sigs = []
        while isinstance(p, _SignaturePacket):
            if p.sigtype != _SignaturePacket.ST_DIRECT:
                raise ValueError, ("Unexpected signature type 0x%02X after "
                                   "public key packet" % p.sigtype)
            self.direct_sigs.append(p)
            p = _popListHead(packets)
        
        # VERIFY: primary key must be capable of signing (on selfsignature)
        # VERIFY: check primary key has not expired (on selfsignature on v4)
        #        (but what if it has?)
        h = {}
        self.user_ids = []
        have_uid = False
        while isinstance(p, (_UserIDPacket, _UserAttributePacket)):
            if isinstance(p, _UserIDPacket):
                have_uid = True
            uid = p
            if not h.has_key(uid):
                sigs = []
                self.user_ids.append((uid, sigs))
                h[uid] = sigs
            else:
                sigs = h[uid]
            new = []
            p = _popListHead(packets)
            while isinstance(p, _SignaturePacket):
                new.append(p)
                p = _popListHead(packets)
            _mergeSigs(sigs, new)
        if not have_uid:
            raise ValueError, "Missing User ID packet"

        self.subkeys = []
        while isinstance(p, _PublicSubkeyPacket):
            subkey = p
            sigs = []
            p = _popListHead(packets)
            while isinstance (p, _SignaturePacket):
                # BADFORMAT: 0x75BE8097, "Florian Lohoff <flo@rfc822.org>"
                # has ceritification signatures on a subkey, we just ignore
                # them
                if p.sigtype != _SignaturePacket.ST_CERT_GENERIC:
                    # Too many keys have revocation signatures after binding
                    # signatures :-(
                    if (p.sigtype != _SignaturePacket.ST_SUBKEY
                        and (p.sigtype
                             != _SignaturePacket.ST_SUBKEY_REVOCATION)):
                        raise ValueError, \
                              ("Unexpected subkey signature type 0x%02X"
                               % p.sigtype)
                    # VERIFY: subkey binding signatures are by the primary key
                    sigs.append(p)
                p = _popListHead(packets)
            self.subkeys.append((subkey, sigs))
        if p is not None:
            raise ValueError, "Unexpected trailing packet of type %s" % p.tag

    def __str__(self):
        ret = ""
        for (uid, _) in self.user_ids:
            # Ignore _UserAttributePackets
            if isinstance(uid, _UserIDPacket):
                if len(ret) != 0:
                    ret += "\naka "
                ret += uid.data
        return ret

    def keyPackets(self):
        """Return key packets in this key."""

        return [self.primary_key] + [subkey for (subkey, _) in self.subkeys]

    def keyIDs(self):
        """Return key IDs of keys in this key."""

        return [packet.keyID() for packet in self.keyPackets()]

    def keyPacketsWithID(self, id):
        """Return a list of key packets maching a key ID."""

        return [packet for packet in self.keyPackets() if packet.keyID() == id]

    def merge(self, other):
        """Merge data from other key with the same unique_id."""

        # One revocation is enough
        # VERIFY: ... assuming it is valid
        if (self.primary_revocation is None
            or self.primary_revocation.hashed_sp["sign_time"] >
            other.primary_revocation.hashed_sp["sign_time"]):
            self.primary_revocation = other.primary_revocation
        
        _mergeSigs(self.direct_sigs, other.direct_sigs)

        h = {}
        for (uid, sigs) in self.user_ids:
            h[uid] = sigs
        for (uid, sigs) in other.user_ids:
            if not h.has_key(uid):
                sigs = sigs.copy()
                self.user_ids.append((uid, sigs))
                h[uid] = sigs
            else:
                _mergeSigs(h[uid], sigs)
        
        h = {}
        for (subkey, sigs) in self.subkeys:
            h[subkey] = sigs
        for (subkey, sigs) in other.subkeys:
            if not h.has_key(subkey):
                sigs = sigs.copy()
                self.subkeys.append((subkey, sigs))
                h[subkey] = sigs
            else:
                _mergeSigs(h[uid], sigs)


def parsePGPKeys(data):
    """Return a list of _PublicKeys parsed from input data."""

    packets = parsePGPMessage(data)
    keys = []
    start = 0;
    while start < len(packets):
        for end in xrange(start + 1, len(packets)):
            if isinstance(packets[end], _PublicKeyPacket):
                break
        else:
            end = len(packets)
        keys.append(_PublicKey(packets[start:end]))
        start = end
    return keys


class PGPKeyRing:
    """A set of keys, allowing lookup by key IDs."""

    def __init__(self):
        # unique_id => key
        self.keys = {}
        self.by_key_id = {}

    def addKey(self, key):
        """Add a _PublicKey."""

        if self.keys.has_key(key.unique_id):
            k = self.keys[key.unique_id]
            k.merge(key)
            key = k
        else:
            self.keys[key.unique_id] = key
        for key_id in key.keyIDs():
            if not self.by_key_id.has_key(key_id):
                self.by_key_id[key_id] = [key]
            else:
                l = self.by_key_id[key_id]
                if key not in l:
                    l.append(key)



if __name__ == "__main__":
    keyring = PGPKeyRing()
    keys = parsePGPKeys(file('key').read())
    for key in keys:
        keyring.addKey(key)
    sig = parsePGPSignature(file('sig').read())
    digest = sig.prepareDigest()
    digest.update(file('BUGS').read())
    print sig.verifyDigest(keyring, sig.finishDigest(digest))
