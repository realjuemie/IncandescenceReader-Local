"use strict";

(() => {
  const STORAGE_KEY = "xglow-language";
  const SUPPORTED = new Set(["zh-CN", "en"]);
  const trackedText = new Set();
  const trackedAttributes = [];

  const staticText = {
    "X拾光 · 账号导航": "XGlow · Account Directory",
    "X拾光 · 会员登录": "XGlow · Member Sign In",
    "X拾光 · X 内容阅读": "XGlow · X Reader",
    "X拾光 · 管理后台": "XGlow · Admin",
    "X拾光 · 页面不存在": "XGlow · Page not found",
    "XGlow · 本地 X 内容导航": "XGlow · Local X Content Directory",
    "XGlow · 管理后台": "XGlow · Admin Console",
    "本地 X 内容导航": "Local X Content Directory",
    "媒体与内容保存在站点本地": "Media and content stay on this site",
    "· 媒体与内容保存在站点本地": "· Media and content stay on this site",
    "关注的人，": "The people you follow,",
    "安静地留在这里。": "quietly kept here.",
    "选择一个账号阅读已保存到本站的内容，或者前往其 X 官方主页。本站不会要求访客登录 X。": "Choose an account to read content saved locally, or visit its official X profile. Visitors never need to sign in to X.",
    "正在读取账号…": "Loading accounts…",
    "账号导航": "Account directory",
    "账号显示方式": "Account layout",
    "切换为横幅显示": "Use banner layout",
    "切换为小组件显示": "Use card layout",
    "横幅": "Banners",
    "组件": "Cards",
    "会员登录": "Member sign in",
    "会员访问": "Member access",
    "登录后可查看管理员分配给你的用户和本地归档内容。": "Sign in to view the accounts and local archive assigned to you.",
    "会员名": "Member ID",
    "密码": "Password",
    "登录并继续": "Sign in and continue",
    "当前会员已登录": "Current member is signed in",
    "继续阅读": "Continue reading",
    "退出当前会员": "Sign out this member",
    "← 返回账号导航": "← Back to account directory",
    "阅读账号": "Reading accounts",
    "关闭侧栏": "Close sidebar",
    "打开账号列表": "Open account list",
    "只读内容站": "Read-only archive",
    "内容和媒体来自站点本地存储": "Content and media come from local storage",
    "这里还没有公开内容": "No public content yet",
    "管理员添加阅读账号并完成首次抓取后，内容会自动出现在这里。": "Content will appear here after an administrator adds an account and completes its first sync.",
    "正在准备阅读页": "Preparing your reader",
    "正在读取账号与最新内容…": "Loading accounts and latest content…",
    "页面走丢了": "This page wandered off",
    "这个地址不存在，可能已经移动或输入有误。": "This address does not exist. It may have moved or been entered incorrectly.",
    "账号不存在或无权访问": "Account unavailable",
    "这个账号地址无效、已被删除，或者当前登录无权查看。": "This account link is invalid, deleted, or unavailable to the current sign-in.",
    "返回账号导航": "Back to account directory",
    "全部": "All",
    "内容类型": "Content type",
    "搜索本站内容": "Search local content",
    "按年月筛选": "Filter by year and month",
    "筛选年份": "Filter year",
    "筛选月份": "Filter month",
    "清除时间筛选": "Clear date filter",
    "原创": "Originals",
    "回复": "Replies",
    "转发": "Reposts",
    "媒体": "Media",
    "全部年份": "All years",
    "全部月份": "All months",
    "加载更早内容": "Load older content",
    "正在读取本站内容…": "Loading local content…",
    "图片预览": "Image preview",
    "关闭图片预览": "Close image preview",
    "管理员登录": "Administrator sign in",
    "登录后管理抓取凭证、阅读账号和自动更新。": "Sign in to manage X credentials, reading accounts, and automatic updates.",
    "管理员密码": "Administrator password",
    "再次输入密码": "Confirm password",
    "登录": "Sign in",
    "← 返回公开阅读页": "← Back to public reader",
    "管理后台": "Admin console",
    "用户管理": "Account management",
    "会员管理": "Member management",
    "通知设置": "Notifications",
    "查看公开站": "View public site",
    "退出登录": "Sign out",
    "抓取与内容管理": "Sync and content management",
    "只有管理员能看到此页面；公开站始终只读。": "Only administrators can see this page; the public site is always read-only.",
    "↻ 立即增量更新全部": "↻ Sync all now",
    "公开账号": "Public accounts",
    "等待读取": "Waiting for data",
    "有效抓取凭证": "Valid X credentials",
    "免费组件": "Free component",
    "自动更新": "Automatic sync",
    "等待状态": "Waiting for status",
    "当前任务": "Current task",
    "运行状态": "System status",
    "无任务": "No task",
    "抓取异常": "Sync issues",
    "以下账号最近一次更新失败。这里会保留具体原因，更新成功后自动移除。": "The accounts below failed during their latest sync. Details remain here until a sync succeeds.",
    "访问 X 的网络代理": "Network proxy for X",
    "中国大陆网络环境通常需要代理。开启后，凭证验证、内容抓取、头像和媒体下载都会使用同一个代理。": "Some networks require a proxy to reach X. When enabled, credential checks, syncing, avatars, and media downloads all use it.",
    "代理地址": "Proxy URL",
    "例如 http://127.0.0.1:7890": "For example, http://127.0.0.1:7890",
    "支持 HTTP、HTTPS、SOCKS5；如有账号密码可直接写在 URL 中": "Supports HTTP, HTTPS, and SOCKS5. Credentials may be included in the URL.",
    "测试连接": "Test connection",
    "保存代理": "Save proxy",
    "Bark 更新通知": "Bark update notifications",
    "增量更新抓到新内容或 X 登录凭证失效时推送；首次归档不会发送历史内容提醒。凭证失效通知会直接定位到后台凭证区域。": "Push when incremental sync finds new content or an X credential expires. Initial archives do not send historical alerts. Credential alerts link back to this panel.",
    "Bark 服务器地址": "Bark server URL",
    "通知分组": "Notification group",
    "站点访问地址": "Public site URL",
    "从 Bark App 复制，留空不修改": "Copy from Bark; leave blank to keep the saved key",
    "例如 http://192.168.1.20:8787": "For example, http://192.168.1.20:8787",
    "Device Key 尚未保存。站点地址建议填写其他设备可以访问的局域网地址。": "No Device Key is saved. Use a LAN address that other devices can reach.",
    "保存后可以发送测试通知": "Save first, then send a test notification",
    "清除密钥": "Clear key",
    "测试推送": "Send test",
    "保存通知设置": "Save notification settings",
    "抓取账号凭证": "X sync credentials",
    "可粘贴完整 Cookie 字符串、Cookie 请求头、Copy as cURL、JSON 或表格；系统只提取所需字段，并在保存前向 X 验证。": "Paste a full Cookie string, Cookie header, Copy as cURL output, JSON, or a table. Only required fields are extracted and verified with X before saving.",
    "检查中": "Checking",
    "会话备注（可选）": "Session label (optional)",
    "留空则使用验证到的 X 用户名": "Leave blank to use the verified X username",
    "等待粘贴 Cookie": "Waiting for Cookie input",
    "完整 Cookie / 请求头 / JSON": "Full Cookie / header / JSON",
    "直接粘贴全部 Cookie；无需手动寻找 auth_token 和 ct0": "Paste the full Cookie; auth_token and ct0 are detected automatically",
    "隐私说明": "Privacy note",
    "原始 Cookie 不会返回到网页，也不会写入日志；验证通过后只保存": "Raw Cookies are never returned to the browser or written to logs. After verification, only",
    "与": "and",
    "。": ".",
    "提取、验证并保存": "Extract, verify, and save",
    "管理抓取用户、内容范围与公开状态。关闭公开展示后，游客无法访问其主页、内容或本地媒体，管理员仍可预览。": "Manage synced accounts, content scope, and visibility. Private accounts are hidden from visitors but remain available to administrators.",
    "添加": "Add",
    "为每个会员单独分配可查看的用户。公开用户仍可被游客查看；非公开用户只有管理员和获授权会员可以访问。": "Assign visible accounts to each member. Public accounts remain open to visitors; private accounts require administrator or member access.",
    "初始密码": "Initial password",
    "创建会员": "Create member",
    "自动增量更新": "Automatic incremental sync",
    "有历史游标时只扫描更新内容，已下载媒体不会重复下载。": "When a history cursor exists, only new content is scanned and downloaded media is not fetched again.",
    "更新间隔（分钟）": "Sync interval (minutes)",
    "首次读取条数": "Initial item limit",
    "增量扫描上限": "Incremental scan limit",
    "媒体并发数": "Media concurrency",
    "单个媒体上限（MB）": "Per-media limit (MB)",
    "保存更新设置": "Save sync settings"
  };

  const messages = {
    "zh-CN": {
      requestFailed: "请求失败 ({status})", refreshedAt: "页面刷新于 {time}", signOut: "退出", memberSignIn: "会员登录",
      memberOnly: "会员专属", adminOnly: "仅管理可见", publicSummary: "{publicCount} 个公开账号{privatePart} · {latestPart}",
      privateSummaryPart: " · {privateCount} 个{label}", latestUpdate: "最近更新 {time}", awaitingFirstSync: "等待首次抓取",
      noPublicAccounts: "管理员尚未添加公开账号", noReadableAccounts: "还没有可阅读的账号",
      noReadableAccountsHelp: "管理员添加账号并完成抓取后，会自动显示在这里。", readerAccountNotFound: "账号不存在或无权访问",
      readerAccountNotFoundHelp: "这个账号地址无效、已被删除，或者当前登录无权查看。", noBio: "暂无个人简介",
      contentCount: "{count} 条内容", mediaCount: "{count} 个媒体", notUpdated: "尚未完成首次更新",
      readAccountAria: "阅读 {name} 的本站内容", readLocal: "阅读本站内容", readShort: "阅读",
      officialAria: "打开 {name} 的 X 官方主页", officialProfile: "X 官方主页 ↗", officialShort: "X 主页",
      memberVisible: "会员可见", adminShort: "仅管理", accountItems: "@{username} · {count} 条",
      yearOption: "{year}年 · {count}条", monthOption: "{month}月 · {count}条", localContent: "本站内容", localMedia: "本站媒体",
      followers: "关注者", trackingSince: "本站自 {time} 开始抓取", trackingUnavailable: "抓取起始时间暂不可用",
      updatedAt: "更新于 {time}", awaitingUpdate: "等待首次更新", unknownTime: "未知时间",
      trackingDate: "{year}年{month}月{day}日 {hour}时{minute}分", noFilteredContent: "当前搜索或时间范围内没有内容",
      noAccountContent: "这个账号还没有已抓取的内容", repost: "转发", quote: "引用", replyingTo: "回复给 ", conversationUser: "对话中的用户",
      mediaUnavailable: "媒体暂时不可用", contentImage: "内容图片", enlargeImage: "放大查看图片", playGif: "播放动图",
      playVideo: "播放视频", gif: "动图", play: "播放", videoUnavailable: "视频暂时无法播放",
      notification: "通知", changePasswordTitle: "点击修改会员密码", memberIdAria: "会员 ID {id}，点击修改密码",
      setupAdmin: "设置管理员密码", setupDescription: "这是首次启动。请创建一个仅用于本站管理后台的密码。",
      createAdmin: "创建密码并进入后台", passwordMismatch: "两次输入的密码不一致",
      syncFailed: "同步失败", rateLimited: "X 请求频率受限，请稍后再试", xTimeout: "连接 X 超时，请检查网络或代理",
      credentialInvalid: "抓取凭证不可用或已经失效", accountMissing: "X 账号不存在、已改名或暂时无法找到",
      protectedAccount: "该账号受保护，当前凭证无权读取", networkFailed: "网络或代理连接失败",
      failuresNeedAction: "{count} 个账号需要处理", failedAt: "失败于 {relative} · {absolute}", failureTimeUnknown: "失败时间未知",
      technicalInfo: "技术信息：{detail}", retrySync: "重新更新", accountMemberTotal: "共 {accounts} 个 · {members} 个会员",
      componentMissing: "组件未安装", scheduleMinutes: "{minutes} 分钟", scheduleOff: "未开启", nextRun: "下次 {time}", noSchedule: "暂无计划",
      running: "运行中", idle: "空闲", lastResult: "上次成功 {ok} / 失败 {failed}", noTask: "无任务",
      noValidCredentials: "v{version} · 无有效凭证", availableCredentials: "v{version} · {count} 个可用",
      cookiesFound: "✓ {format}：已自动找到 auth_token 和 ct0", cookiesMissing: "还缺少：{items}", pasteCookie: "请先粘贴 Cookie",
      validatingX: "正在向 X 验证…", cookieValidated: "验证通过，原始 Cookie 已从表单清除", credentialSaved: "凭证验证有效并已保存{username}",
      noCredentials: "尚无抓取凭证。粘贴完整 Cookie 后，系统会自动提取并验证。", verifiedDetail: "已验证{username}{time} · 已请求 {count} 次",
      validationFailed: "验证失败，请导入新的 Cookie", legacyCredential: "旧凭证尚未在线验证", validateAgain: "重新验证", deleteAction: "删除",
      credentialValid: "“{label}”验证有效", deleteCredential: "删除抓取凭证“{label}”？", credentialDeleted: "抓取凭证已删除",
      accountAdded: "已添加 @{username}，可执行首次更新", noAccounts: "尚未添加阅读用户。", adminOnlySuffix: " · 仅管理可见",
      accountMeta: "{tweets} 条内容 · {media} 个媒体 · {updated}", syncFailure: "抓取失败：{error}", cursor: "增量游标 {id}", firstSyncHint: "首次更新会读取最近内容",
      publicDisplay: "公开展示", replies: "回复", reposts: "转发", saveSettings: "保存设置", syncing: "更新中…", syncNow: "立即更新", preview: "预览", temporaryShare: "临时分享",
      temporaryShareTitle: "创建临时分享链接", temporaryShareIntro: "链接仅允许浏览 @{username} 的本站内容，到期后自动失效。", validFor: "有效时长", timeUnit: "单位", hours: "小时", days: "天", minutes: "分钟", shareLink: "分享链接", createAndCopy: "创建并复制", creatingShare: "正在创建安全链接…", shareCopiedUntil: "链接已复制，有效至 {time}", shareCopied: "临时分享链接已复制", copyFailed: "浏览器未允许自动复制，请手动复制上方链接", close: "关闭",
      memberCreated: "会员 {username} 已创建，请为其分配可查看用户", noMembers: "尚未创建会员。会员登录后只能看到公开用户和分配给自己的非公开用户。",
      lastLogin: "上次登录 {time}", createdAt: "创建于 {time}", unsavedChanges: "有未保存更改", allowLogin: "允许登录", visibleAccounts: "可查看的用户",
      addAccountsFirst: "请先添加抓取用户", publicSuffix: "（公开）", privateSuffix: "（非公开）", resetPasswordPlaceholder: "留空不改密码；输入新密码可重置",
      savePermissions: "保存权限", deleteMember: "删除会员", permissionsSaved: "会员 {username} 的权限已保存", confirmDeleteMember: "删除会员 {username}？请输入会员名确认：",
      memberDeleted: "会员 {username} 已删除", barkFailed: "；Bark 失败：{error}", syncAccountDone: "@{username} 更新完成：新增 {inserted} 条，媒体 {media} 个{notice}",
      accountSettingsSaved: "用户设置已保存", confirmDeleteAccount: "这会删除 @{username} 的数据库记录和本地媒体。请输入账号名确认：", accountDeleted: "@{username} 已删除",
      syncAccountFailed: "@{username} 更新失败：{error}", keySavedPlaceholder: "已安全保存，留空不修改", keyCopyPlaceholder: "从 Bark App 复制 Device Key",
      keySavedHelp: "Device Key 已保存且不会回传到网页。站点地址建议填写手机可访问的局域网地址。", keyMissingHelp: "Device Key 尚未保存。站点地址建议填写其他设备可以访问的局域网地址。",
      barkKeyRequired: "开启 Bark 推送前请填写 Device Key", barkEnabledSaved: "设置已保存；仅在后续增量抓到新内容时推送", barkDisabledSaved: "设置已保存，Bark 推送当前关闭",
      barkSaved: "Bark 通知设置已保存", unsavedKey: "Device Key 有未保存的修改，请先保存通知设置", saveKeyFirst: "请先填写并保存 Bark Device Key",
      sendingBarkTest: "正在发送 Bark 测试通知…", barkTestDelivered: "测试推送已送达 · HTTP {status} · {elapsed} ms", barkTestSent: "Bark 测试通知已发送",
      confirmClearBark: "清除已保存的 Bark Device Key 并关闭推送？", barkKeyCleared: "Bark Device Key 已清除", barkClearedToast: "Bark 密钥已清除",
      proxyRequired: "请填写代理地址", testingProxy: "正在通过代理连接 X…", proxyConnected: "连接成功 · HTTP {status} · {elapsed} ms", proxyWorks: "代理可以访问 X",
      proxyEnabledSaved: "代理设置已保存；后续网络请求将使用此代理", proxyDisabled: "代理已关闭", proxySaved: "代理设置已保存", schedulerSaved: "自动更新设置已保存",
      barkFailureCount: "，Bark 失败 {count}", syncAllFailures: "更新完成：成功 {ok}，失败 {failed}（{accounts}）；详情已列在页面顶部{notice}",
      syncAllDone: "更新完成：成功 {ok}，失败 {failed}{notice}", loadingNotifications: "正在读取通知设置…", myBark: "我的 Bark 通知",
      personalAlertIntro: "只向你的 Bark 推送所选账号的新内容。Device Key 仅保存在本站，不会回传到网页。", enableMyAlerts: "开启我的通知",
      chooseAlertAccounts: "选择需要通知的账号", test: "测试", save: "保存", savedKeyShort: "已安全保存，留空不修改", copyFromBark: "从 Bark App 复制",
      public: "公开", noSubscriptions: "当前没有可订阅的账号。", keySavedSubscriptions: "Device Key 已保存，可直接修改订阅账号。", enterBarkKey: "请先填写 Bark Device Key。",
      saving: "正在保存…", memberAlertsEnabled: "已开启所选账号的新内容通知。", memberAlertsDisabled: "设置已保存，通知当前关闭。", memberAlertsSaved: "个人 Bark 通知设置已保存",
      unsavedMemberKey: "Device Key 有未保存的修改，请先保存。", saveMemberKeyFirst: "请先填写并保存 Device Key。", sendingTest: "正在发送测试通知…",
      testDelivered: "测试通知已送达 · HTTP {status} · {elapsed} ms", confirmClearMemberKey: "清除你的 Bark Device Key 并关闭通知？", memberKeyCleared: "Device Key 已清除，个人通知已关闭。",
      changeMemberPassword: "修改会员密码", currentMemberIntro: "当前会员 ID：", passwordChangeWarning: "。修改后，其他设备上的旧登录会失效。",
      currentPassword: "当前密码", newPassword: "新密码", confirmNewPassword: "再次输入新密码", cancel: "取消", updatePassword: "更新密码",
      newPasswordMismatch: "两次输入的新密码不一致。", updatingPassword: "正在更新密码…", passwordUpdated: "会员密码已更新，其他设备需要重新登录"
    },
    en: {
      requestFailed: "Request failed ({status})", refreshedAt: "Refreshed at {time}", signOut: "Sign out", memberSignIn: "Member sign in",
      memberOnly: "Members only", adminOnly: "Admin only", publicSummary: "{publicCount} public accounts{privatePart} · {latestPart}",
      privateSummaryPart: " · {privateCount} {label}", latestUpdate: "Updated {time}", awaitingFirstSync: "Awaiting first sync",
      noPublicAccounts: "No public accounts have been added", noReadableAccounts: "No readable accounts yet",
      noReadableAccountsHelp: "Accounts will appear here after an administrator adds and syncs them.", readerAccountNotFound: "Account unavailable",
      readerAccountNotFoundHelp: "This account link is invalid, deleted, or unavailable to the current sign-in.", noBio: "No bio available",
      contentCount: "{count} posts", mediaCount: "{count} media", notUpdated: "First sync not completed",
      readAccountAria: "Read locally saved content from {name}", readLocal: "Read local content", readShort: "Read",
      officialAria: "Open {name}'s official X profile", officialProfile: "X profile ↗", officialShort: "X profile",
      memberVisible: "Member access", adminShort: "Admin only", accountItems: "@{username} · {count} posts",
      yearOption: "{year} · {count} posts", monthOption: "{month} · {count} posts", localContent: "Local posts", localMedia: "Local media",
      followers: "Followers", trackingSince: "Tracking since {time}", trackingUnavailable: "Tracking start time unavailable",
      updatedAt: "Updated {time}", awaitingUpdate: "Awaiting first update", unknownTime: "Unknown time",
      trackingDate: "{month}/{day}/{year} {hour}:{minute}", noFilteredContent: "No content matches the current search or date range",
      noAccountContent: "No synced content for this account yet", repost: "Repost", quote: "Quote", replyingTo: "Replying to ", conversationUser: "someone in the conversation",
      mediaUnavailable: "Media temporarily unavailable", contentImage: "Post image", enlargeImage: "Open image preview", playGif: "Play animation",
      playVideo: "Play video", gif: "Animation", play: "Play", videoUnavailable: "Video temporarily unavailable",
      notification: "Alerts", changePasswordTitle: "Change member password", memberIdAria: "Member ID {id}; change password",
      setupAdmin: "Set administrator password", setupDescription: "This is the first launch. Create a password used only for this admin console.",
      createAdmin: "Create password and continue", passwordMismatch: "The passwords do not match",
      syncFailed: "Sync failed", rateLimited: "X rate-limited the request. Try again later.", xTimeout: "X connection timed out. Check the network or proxy.",
      credentialInvalid: "The X credential is unavailable or expired", accountMissing: "The X account is missing, renamed, or temporarily unavailable",
      protectedAccount: "This account is protected and the current credential cannot read it", networkFailed: "Network or proxy connection failed",
      failuresNeedAction: "{count} accounts need attention", failedAt: "Failed {relative} · {absolute}", failureTimeUnknown: "Failure time unavailable",
      technicalInfo: "Technical details: {detail}", retrySync: "Retry sync", accountMemberTotal: "{accounts} accounts · {members} members",
      componentMissing: "Component not installed", scheduleMinutes: "{minutes} min", scheduleOff: "Off", nextRun: "Next {time}", noSchedule: "Not scheduled",
      running: "Running", idle: "Idle", lastResult: "Last: {ok} succeeded / {failed} failed", noTask: "No task",
      noValidCredentials: "v{version} · no valid credentials", availableCredentials: "v{version} · {count} available",
      cookiesFound: "✓ {format}: auth_token and ct0 found", cookiesMissing: "Missing: {items}", pasteCookie: "Paste a Cookie first",
      validatingX: "Validating with X…", cookieValidated: "Validated; raw Cookie removed from the form", credentialSaved: "Credential validated and saved{username}",
      noCredentials: "No X credentials yet. Paste a full Cookie to extract and validate it.", verifiedDetail: "Verified{username}{time} · {count} requests",
      validationFailed: "Validation failed; import a new Cookie", legacyCredential: "Legacy credential has not been verified online", validateAgain: "Validate again", deleteAction: "Delete",
      credentialValid: "“{label}” is valid", deleteCredential: "Delete X credential “{label}”?", credentialDeleted: "X credential deleted",
      accountAdded: "Added @{username}; ready for its first sync", noAccounts: "No reading accounts added.", adminOnlySuffix: " · admin only",
      accountMeta: "{tweets} posts · {media} media · {updated}", syncFailure: "Sync failed: {error}", cursor: "Incremental cursor {id}", firstSyncHint: "The first sync reads recent content",
      publicDisplay: "Public", replies: "Replies", reposts: "Reposts", saveSettings: "Save settings", syncing: "Syncing…", syncNow: "Sync now", preview: "Preview", temporaryShare: "Temporary link",
      temporaryShareTitle: "Create temporary access link", temporaryShareIntro: "This link grants read-only access to @{username} until it expires.", validFor: "Valid for", timeUnit: "Unit", hours: "Hours", days: "Days", minutes: "Minutes", shareLink: "Share link", createAndCopy: "Create and copy", creatingShare: "Creating secure link…", shareCopiedUntil: "Link copied; valid until {time}", shareCopied: "Temporary link copied", copyFailed: "The browser blocked automatic copying; copy the link above manually", close: "Close",
      memberCreated: "Member {username} created; assign visible accounts next", noMembers: "No members yet. Signed-in members see public accounts and private accounts assigned to them.",
      lastLogin: "Last sign-in {time}", createdAt: "Created {time}", unsavedChanges: "Unsaved changes", allowLogin: "Allow sign-in", visibleAccounts: "Visible accounts",
      addAccountsFirst: "Add synced accounts first", publicSuffix: " (public)", privateSuffix: " (private)", resetPasswordPlaceholder: "Leave blank to keep password; enter a new one to reset",
      savePermissions: "Save access", deleteMember: "Delete member", permissionsSaved: "Saved access for member {username}", confirmDeleteMember: "Delete member {username}? Enter the member ID to confirm:",
      memberDeleted: "Member {username} deleted", barkFailed: "; Bark failed: {error}", syncAccountDone: "@{username} synced: {inserted} new posts, {media} media{notice}",
      accountSettingsSaved: "Account settings saved", confirmDeleteAccount: "This deletes @{username}'s database records and local media. Enter the username to confirm:", accountDeleted: "@{username} deleted",
      syncAccountFailed: "@{username} sync failed: {error}", keySavedPlaceholder: "Saved securely; leave blank to keep it", keyCopyPlaceholder: "Copy Device Key from Bark",
      keySavedHelp: "The Device Key is saved and never returned to the browser. Use a LAN address reachable from your phone.", keyMissingHelp: "No Device Key is saved. Use a LAN address reachable from other devices.",
      barkKeyRequired: "Enter a Device Key before enabling Bark", barkEnabledSaved: "Saved; new-content alerts will be sent after future incremental syncs", barkDisabledSaved: "Saved; Bark notifications are off",
      barkSaved: "Bark notification settings saved", unsavedKey: "The Device Key has unsaved changes. Save notification settings first.", saveKeyFirst: "Enter and save a Bark Device Key first.",
      sendingBarkTest: "Sending Bark test…", barkTestDelivered: "Test delivered · HTTP {status} · {elapsed} ms", barkTestSent: "Bark test notification sent",
      confirmClearBark: "Clear the saved Bark Device Key and disable notifications?", barkKeyCleared: "Bark Device Key cleared", barkClearedToast: "Bark key cleared",
      proxyRequired: "Enter a proxy URL", testingProxy: "Connecting to X through the proxy…", proxyConnected: "Connected · HTTP {status} · {elapsed} ms", proxyWorks: "The proxy can reach X",
      proxyEnabledSaved: "Proxy saved; future network requests will use it", proxyDisabled: "Proxy disabled", proxySaved: "Proxy settings saved", schedulerSaved: "Automatic sync settings saved",
      barkFailureCount: ", {count} Bark failures", syncAllFailures: "Sync complete: {ok} succeeded, {failed} failed ({accounts}). Details are listed above{notice}",
      syncAllDone: "Sync complete: {ok} succeeded, {failed} failed{notice}", loadingNotifications: "Loading notification settings…", myBark: "My Bark alerts",
      personalAlertIntro: "Send new-content alerts from selected accounts to your Bark only. The Device Key stays on this site and is never returned to the browser.", enableMyAlerts: "Enable my alerts",
      chooseAlertAccounts: "Choose accounts to notify", test: "Test", save: "Save", savedKeyShort: "Saved securely; leave blank to keep it", copyFromBark: "Copy from Bark",
      public: "Public", noSubscriptions: "No accounts are currently available for alerts.", keySavedSubscriptions: "Device Key saved; you can change subscribed accounts.", enterBarkKey: "Enter a Bark Device Key first.",
      saving: "Saving…", memberAlertsEnabled: "New-content alerts are enabled for the selected accounts.", memberAlertsDisabled: "Settings saved; alerts are currently off.", memberAlertsSaved: "Personal Bark alert settings saved",
      unsavedMemberKey: "The Device Key has unsaved changes. Save first.", saveMemberKeyFirst: "Enter and save a Device Key first.", sendingTest: "Sending test notification…",
      testDelivered: "Test delivered · HTTP {status} · {elapsed} ms", confirmClearMemberKey: "Clear your Bark Device Key and disable alerts?", memberKeyCleared: "Device Key cleared; personal alerts are off.",
      changeMemberPassword: "Change member password", currentMemberIntro: "Current member ID: ", passwordChangeWarning: ". Other devices will be signed out after the change.",
      currentPassword: "Current password", newPassword: "New password", confirmNewPassword: "Confirm new password", cancel: "Cancel", updatePassword: "Update password",
      newPasswordMismatch: "The new passwords do not match.", updatingPassword: "Updating password…", passwordUpdated: "Member password updated; other devices must sign in again"
    }
  };

  const englishErrors = {
    "管理员密码已经设置": "The administrator password is already configured",
    "请先设置管理员密码": "Set an administrator password first",
    "管理员凭证文件损坏": "The administrator credential file is damaged",
    "管理员密码不正确": "Incorrect administrator password",
    "管理员密码至少需要 10 个字符": "The administrator password must be at least 10 characters",
    "管理员密码过长": "The administrator password is too long",
    "会员名只能使用 3–32 位字母、数字、点、下划线或短横线": "Member IDs must be 3–32 letters, numbers, dots, underscores, or hyphens",
    "会员密码至少需要 8 个字符": "The member password must be at least 8 characters",
    "会员密码过长": "The member password is too long",
    "临时链接有效期无效": "The temporary link duration is invalid",
    "临时链接有效期需要在 5 分钟到 90 天之间": "Temporary links must last from 5 minutes to 90 days",
    "会员名或密码不正确": "Incorrect member ID or password",
    "当前密码不正确": "The current password is incorrect",
    "会员不存在": "Member not found",
    "账号不存在": "Account not found",
    "拒绝访问": "Access denied",
    "需要管理员登录": "Administrator sign-in required",
    "需要会员登录": "Member sign-in required",
    "接口不存在": "API endpoint not found",
    "页面不存在": "Page not found",
    "文件不存在": "File not found",
    "请求内容过大": "The request body is too large",
    "JSON 格式无效": "Invalid JSON",
    "请求内容必须是对象": "The request body must be an object",
    "X 用户名只能包含字母、数字、下划线，长度为 1–15 个字符": "X usernames must contain 1–15 letters, numbers, or underscores",
    "年份筛选无效": "Invalid year filter",
    "月份筛选无效": "Invalid month filter",
    "请选择年份后再筛选月份": "Choose a year before filtering by month",
    "分页游标无效": "Invalid pagination cursor",
    "代理地址格式无效": "Invalid proxy URL",
    "代理仅支持 http://、https:// 或 socks5://": "The proxy must use http://, https://, or socks5://",
    "代理地址缺少主机名": "The proxy URL is missing a host",
    "代理地址必须包含端口，例如 http://127.0.0.1:7890": "The proxy URL must include a port, for example http://127.0.0.1:7890",
    "代理地址不能包含路径、查询参数或片段": "The proxy URL cannot include a path, query, or fragment",
    "Bark Device Key 格式无效": "Invalid Bark Device Key",
    "Cookie 不能为空": "Cookie cannot be empty",
    "Cookie 必须同时包含 auth_token 和 ct0": "Cookie must include both auth_token and ct0",
    "Cookie 已失效或不是已登录的 X 会话": "The Cookie has expired or is not a signed-in X session",
    "没有可用的 X 登录会话，请在设置中添加 Cookie": "No X session is available. Add a Cookie in settings.",
    "已有同步任务正在运行，请稍后再试": "A sync is already running. Try again later.",
    "开启 Bark 推送前请至少选择一个通知账号": "Select at least one account before enabling Bark alerts",
    "通知账号列表格式无效": "Invalid notification account list",
    "通知账号中包含当前会员无权访问的账号": "The notification list contains an account this member cannot access"
  };

  function readLocale() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return SUPPORTED.has(saved) ? saved : "zh-CN";
    } catch (_) {
      return "zh-CN";
    }
  }

  let locale = readLocale();

  function interpolate(value, variables = {}) {
    return String(value).replace(/\{([A-Za-z0-9_]+)\}/g, (_, key) => String(variables[key] ?? ""));
  }

  function t(key, variables = {}) {
    const table = messages[locale] || messages["zh-CN"];
    return interpolate(table[key] ?? messages["zh-CN"][key] ?? key, variables);
  }

  function localeTag() {
    return locale === "en" ? "en" : "zh-CN";
  }

  function localizeError(message) {
    const value = String(message || "");
    if (locale !== "en") return value;
    const exact = englishErrors[value] || staticText[value];
    if (exact) return exact;
    const patterns = [
      [/^请求失败\s*\((\d+)\)$/, "Request failed ($1)"],
      [/^账号 @(.+) 已存在$/, "Account @$1 already exists"],
      [/^会员 (.+) 已存在$/, "Member $1 already exists"],
      [/^找不到账号 @(.+)$/, "Account @$1 not found"],
      [/^没有找到必需 Cookie：(.+)$/, "Required Cookie values not found: $1"],
      [/^Cookie (.+) 的值无效$/, "Cookie $1 has an invalid value"],
      [/^媒体超过 (\d+) MB 限制$/, "Media exceeds the $1 MB limit"],
    ];
    for (const [pattern, replacement] of patterns) {
      if (pattern.test(value)) return value.replace(pattern, replacement);
    }
    return value;
  }

  function discover(root = document) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const key = node.nodeValue.trim();
      if (!key || !staticText[key] || trackedText.has(node)) continue;
      trackedText.add(node);
      node.__xglowSourceText = key;
    }
    for (const element of root.querySelectorAll?.("[placeholder], [aria-label], [title]") || []) {
      for (const name of ["placeholder", "aria-label", "title"]) {
        const key = element.getAttribute(name)?.trim();
        if (!key || !staticText[key]) continue;
        if (trackedAttributes.some((item) => item.element === element && item.name === name)) continue;
        trackedAttributes.push({ element, name, key });
      }
    }
  }

  function updateToggleButtons() {
    document.querySelectorAll("[data-language-toggle]").forEach((button) => {
      const target = locale === "en" ? "中文" : "English";
      button.setAttribute("aria-label", locale === "en" ? "切换到中文" : "Switch to English");
      button.title = locale === "en" ? "切换到中文" : "Switch to English";
      const label = button.querySelector("[data-language-label]");
      if (label) label.textContent = locale === "en" ? "中" : "EN";
      button.dataset.languageTarget = target;
    });
  }

  function renderTracked() {
    document.documentElement.lang = localeTag();
    for (const node of trackedText) {
      if (!node.isConnected) continue;
      const source = node.__xglowSourceText;
      const translated = locale === "en" ? staticText[source] : source;
      const leading = node.nodeValue.match(/^\s*/)?.[0] || "";
      const trailing = node.nodeValue.match(/\s*$/)?.[0] || "";
      node.nodeValue = `${leading}${translated}${trailing}`;
    }
    for (const item of trackedAttributes) {
      if (!item.element.isConnected) continue;
      item.element.setAttribute(item.name, locale === "en" ? staticText[item.key] : item.key);
    }
    updateToggleButtons();
  }

  function apply(root = document) {
    discover(root);
    renderTracked();
  }

  function setLocale(next) {
    locale = next === "en" ? "en" : "zh-CN";
    try { localStorage.setItem(STORAGE_KEY, locale); } catch (_) { /* storage unavailable */ }
    renderTracked();
    window.dispatchEvent(new CustomEvent("xglow:localechange", { detail: { locale } }));
  }

  function toggle() {
    setLocale(locale === "en" ? "zh-CN" : "en");
  }

  function bind() {
    apply(document);
    document.querySelectorAll("[data-language-toggle]").forEach((button) => {
      if (button.dataset.languageBound) return;
      button.dataset.languageBound = "true";
      button.addEventListener("click", toggle);
    });
  }

  window.XGlowI18n = {
    t, apply, setLocale, toggle, localeTag, localizeError,
    get locale() { return locale; },
  };
  bind();
})();
