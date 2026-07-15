import xmlrpc.client

class OdooModelWrapper:
    """Odoo ORM mimarisini XML-RPC üzerinden taklit eden profesyonel sarmalayıcı sınıf."""
    def __init__(self, execute_kw, db, uid, pwd, model):
        self._execute_kw = execute_kw
        self._db = db
        self._uid = uid
        self._pwd = pwd
        self._model = model

    def search(self, domain, **kwargs):
        return self._execute_kw(self._db, self._uid, self._pwd, self._model, 'search', [domain], kwargs)
    
    def search_read(self, domain, fields=None, **kwargs):
        if fields: kwargs['fields'] = fields
        return self._execute_kw(self._db, self._uid, self._pwd, self._model, 'search_read', [domain], kwargs)
        
    def read(self, ids, fields=None, **kwargs):
        if fields: kwargs['fields'] = fields
        return self._execute_kw(self._db, self._uid, self._pwd, self._model, 'read', [ids], kwargs)
        
    def write(self, ids, vals):
        return self._execute_kw(self._db, self._uid, self._pwd, self._model, 'write', [ids, vals])

    def unlink(self, ids):
        return self._execute_kw(self._db, self._uid, self._pwd, self._model, 'unlink', [ids])

    def __getattr__(self, method):
        def wrapper(*args, **kwargs):
            return self._execute_kw(self._db, self._uid, self._pwd, self._model, method, list(args), kwargs)
        return wrapper

class OdooEnv:
    def __init__(self, execute_kw, db, uid, pwd):
        self._execute_kw = execute_kw
        self._db = db
        self._uid = uid
        self._pwd = pwd
        self.uid = uid

    def __getitem__(self, model):
        return OdooModelWrapper(self._execute_kw, self._db, self._uid, self._pwd, model)
