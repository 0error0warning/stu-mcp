# 外卖查询与选餐

## 找店与餐段

1. 用户按商家、商品或平台分类找店时，用 `search_takeout_shops`，从返回的 `areas` 和 `categories` 确定区域与分类。餐段对应多个分类时从 `category_options` 选择。餐段分类与配送区域取交集。`area_id="0"` 表示全部区域，省略则用宿主默认区域。问题涉及具体校区时使用对应区域，区分本部、东校区和各自宵夜区域，不默默切换校区。区域不明确且影响结果时问用户。
2. 用户关心某区域某个实际餐段时，用 `find_takeout_meal_shops` 并传明确的 `area_id` 和 `meal_period`。用 `YYYY-MM-DD` 传所需日期，省略为北京时间今天。该工具 `include_closed` 默认为 `false`（仅列有未截单批次的条目；需要核对已截单或停用批次时传 `include_closed=true`）。本部普通商家可能未被放进平台的午餐或晚餐分类，分类为空时可按返回的后续调用核对**同一区域**的实际批次。
3. 实际餐段工具每次扫描默认 5 条、最多 10 条目录记录。沿 `next_offset` 查下一页，按 `has_more` 报告是否覆盖完整。用 `matched_in_page` 表示本页命中。将 `unknown_items` 单列，可能是无固定批次、来源格式未识别或读取失败。本页无命中或时间未知时保留结论范围，尤其是即时配送。

## 核对具体店铺

- 用查店结果给出的 `shop_id` 调 `get_takeout_shop` 看公开详情。用户关心最晚何时选餐或几点送达时，调用 `get_takeout_delivery_slots` 查看指定日期、餐段的配送批次。
- 将配送时段、营业时间、`cutoff_at` 和 `time_status` 分别说明。`passes_time_constraints=true` 只覆盖截单和预订日期窗口，库存、实际营业及地址配送仍需核对。批次餐段可以从时间推断，平台分类是独立字段。`get_takeout_delivery_slots` 默认 `include_closed=true`（同时返回已截单与停用批次供核对）；只需查看未截单或状态未知批次时传 `include_closed=false`。

## 看菜单与生成清单

- 用 `get_takeout_menu` 按名称或分类筛选商品，按 `next_offset` 续页。需要规格、加价或展示价时，用菜单给出的 `product_id` 调 `get_takeout_product`。
- 用户想要选餐清单时，调用 `prepare_takeout_selection`，传单店的 `shop_id` 和 1–10 项不重复的 `items`。每项仅传该店不同的 `product_id` 与整数 `quantity`（1–9）。普通标价合计未计规格、优惠、包装和配送。清单供用户到微信核对规格、地址和实际应付金额，工具不会下单或付款。

外卖数据来自第三方。返回 `takeout_not_configured` 时，由操作者在 MCP 宿主导入配置。签名材料留在宿主，不在对话中索取。
