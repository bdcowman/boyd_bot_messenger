import hashlib
from cryptography.fernet import Fernet


class Guard:
    def __init__(self, key):
        self.guard = Fernet(key)

    def encrypt(self, val):
        return self.guard.encrypt(val.encode())

    def decrypt(self, val):
        return (self.guard.decrypt(val)).decode()

    def sha256(self, val):
        return hashlib.sha256(val.encode()).hexdigest()

    def sanitized(self, request, key, val=None, db=None):
        result = False
        request = [request] if not isinstance(request, list) else request
        key = [key] if not isinstance(key, list) else key

        for r in request:
            for k in key:
                if k in r:
                    result = True
                    if val:
                        result = True if r[k] == val else False
                    if db:
                        uid = r[k]
                        result = result and (db.check_reg_data(uid) or db.get_data(uid))
                    break

        return result
