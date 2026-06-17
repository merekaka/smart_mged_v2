class CacheRouter:
    """
    数据库路由：
    - query_cache  应用中的缓存模型使用 cache_sqlite 数据库
    - chat         应用中的对话管理模型使用 cache_sqlite 数据库
    其他应用默认使用 default 数据库（MySQL）。
    """
    route_app_labels = {'query_cache', 'chat'}

    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.route_app_labels:
            return 'cache_sqlite'
        return 'default'

    def db_for_write(self, model, **hints):
        if model._meta.app_label in self.route_app_labels:
            return 'cache_sqlite'
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        # 如果两个对象都在被路由到 cache_sqlite 的 app 中，允许建立关系
        if (
            obj1._meta.app_label in self.route_app_labels and
            obj2._meta.app_label in self.route_app_labels
        ):
            return True
        # 如果任意一方在路由 app 中而另一方不在，禁止跨库关系
        if (
            obj1._meta.app_label in self.route_app_labels or
            obj2._meta.app_label in self.route_app_labels
        ):
            return False
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.route_app_labels:
            return db == 'cache_sqlite'
        return db == 'default'
