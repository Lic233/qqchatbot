"""In-memory state shared by message handlers."""
last_messages = {}
last_faces = {}
last_images = {}
pending_catgirl_requests = {}
# 机器人在各群的群名片/昵称，用于识别手打的“@名字”
bot_group_names = {}
bot_group_name_requested = set()
pending_bot_name_requests = {}
