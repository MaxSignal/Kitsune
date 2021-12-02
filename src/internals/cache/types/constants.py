from configs.env_vars import ENV_VARS

node_options = dict(
    host=ENV_VARS.REDIS_HOST,
    port=ENV_VARS.REDIS_PORT,
    password=ENV_VARS.REDIS_PASSWORD
)

nodes = {
    0: {'db': 0}
}
