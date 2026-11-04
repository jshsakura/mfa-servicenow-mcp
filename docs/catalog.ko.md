# 서비스 카탈로그

도구 하나, `manage_catalog`로 서비스 카탈로그 카테고리(`sc_category`), 항목(`sc_cat_item`), 항목 변수(`item_option_new`)를 다룹니다.

| 패키지 | 액션 |
|---|---|
| `service_desk` | 읽기 액션 4개 |
| `portal_developer`, `full` | 모든 액션 |

쓰기 액션은 이 서버의 다른 쓰기와 마찬가지로 `confirm='approve'`가 필요합니다.

## 읽기 액션

| 액션 | 인자 | 반환 |
|---|---|---|
| `action="list_categories"` | `limit`, `offset`, `query`, `active`, `count_only` | 카테고리 목록 |
| `action="list_items"` | `limit`, `offset`, `query`, `category`, `active`, `count_only` | 항목 목록 |
| `action="get_item"` | `item_id` | 항목과 그 변수 |
| `action="list_item_variables"` | `catalog_item_id` | 변수 목록: 이름, 라벨, 타입 코드, 필수 여부, 기본값, 순서 |

두 목록 액션이 돌려주는 값:

- `count`: 이번 페이지의 건수입니다.
- `total`: 서버에서 조건에 맞는 전체 건수입니다.
- `more`: 다음 페이지가 있을 때만 나오며, 다음에 요청할 offset도 함께 알려 줍니다.

서버가 전체 건수를 보내지 않으면 추측하지 않고 `total_unknown`으로 표시합니다. `count_only=true`를 주면 건수만 돌려줍니다.

## 쓰기 액션

| 액션 | 필수 | 선택 |
|---|---|---|
| `action="create_category"` | `title` | `description`, `parent`, `icon`, `active`, `order` |
| `action="update_category"` | `category_id`와 필드 하나 이상 | create와 같은 필드 |
| `action="update_item"` | `item_id`와 필드 하나 이상 | `name`, `short_description`, `description`, `category`, `price`, `active`, `order` |
| `action="move_items"` | `item_ids`, `target_category_id` | |
| `action="create_variable"` | `catalog_item_id`, `variable_name`, `variable_type`, `label` | `mandatory`, `help_text`, `default_value`, `description`, `order`, `reference_table`, `reference_qualifier`, `max_length`, `min`, `max` |
| `action="update_variable"` | `variable_id`와 필드 하나 이상 | `variable_name`, `variable_type`, `reference_table`, create의 선택 필드 |

### 변수 타입

`item_option_new.type`에는 단어가 아니라 숫자 코드가 저장됩니다. 코드나 라벨 중 하나를 넘기면 됩니다.

| 코드 | 라벨 |
|---|---|
| `6` | Single Line Text |
| `2` | Multi Line Text |
| `5` | Select Box |
| `3` | Multiple Choice |
| `7` | CheckBox |
| `8` | Reference |
| `9` | Date |
| `10` | Date/Time |

쓰기 전에 그 인스턴스의 선택지 목록(`sys_choice`)과 대조하므로, 인스턴스에서 추가한 선택지도 받습니다. 목록에 없는 값은 거절하고, 사용할 수 있는 코드를 모두 알려 줍니다. 선택지 목록을 읽지 못하면 아무것도 쓰지 않습니다.

### 길이와 범위

- `item_option_new`에는 `max_length` 컬럼이 없습니다. `max_length`는 플랫폼과 같은 방식으로 변수의 `attributes`에 `max_length=N` 형태로 저장됩니다.
- `min`과 `max`는 평가 척도(rating scale)의 범위인 `scale_min`, `scale_max`를 설정합니다.

## 미리보기

모든 쓰기 액션에 `dry_run=true`를 줄 수 있습니다.

- `action="update_category"`와 `action="update_item"`은 필드별 차이를 보여 줍니다.
- 그 밖의 쓰기 액션은 보낼 요청을 그대로 `would_send`로 돌려줍니다.

어느 경우든 아무것도 쓰지 않습니다. 이 규칙은 서버가 모든 도구에 대해 강제하므로, 미리보기가 실제 쓰기로 바뀌는 일은 없습니다.

## 프롬프트 예시

- "카탈로그 카테고리와 카테고리별 항목 수를 보여줘."
- "'New Laptop' 항목의 변수들을 보여줘."
- "그 항목에 필수 Single Line Text 변수 'asset_tag'를 추가해 줘. 먼저 미리보기로."
- "이 세 항목을 Hardware 카테고리로 옮겨 줘."
