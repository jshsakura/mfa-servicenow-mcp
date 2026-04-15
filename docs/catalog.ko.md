# ServiceNow 서비스 카탈로그 연동

이 문서는 ServiceNow MCP 서버의 ServiceNow 서비스 카탈로그 연동에 대한 정보를 제공합니다.

## 개요

ServiceNow 서비스 카탈로그 연동을 통해 다음 작업을 수행할 수 있습니다.

- 서비스 카탈로그 카테고리 목록 조회
- 서비스 카탈로그 항목 목록 조회
- 특정 카탈로그 항목의 상세 정보(변수 포함) 확인
- 카테고리 또는 검색어로 카탈로그 항목 필터링

## 도구

ServiceNow 서비스 카탈로그와 상호작용하기 위한 도구는 다음과 같습니다.

### `list_catalog_categories`

사용 가능한 서비스 카탈로그 카테고리를 조회합니다.

**매개변수:**
- `limit` (int, 기본값: 10): 반환할 최대 카테고리 수
- `offset` (int, 기본값: 0): 페이지네이션 오프셋
- `query` (string, 선택): 카테고리 검색어
- `active` (boolean, 기본값: true): 활성 카테고리만 반환할지 여부

**예시:**
```python
from servicenow_mcp.tools.catalog_tools import ListCatalogCategoriesParams, list_catalog_categories

params = ListCatalogCategoriesParams(
    limit=5,
    query="hardware"
)
result = list_catalog_categories(config, auth_manager, params)
```

### `create_catalog_category`

새로운 서비스 카탈로그 카테고리를 생성합니다.

**매개변수:**
- `title` (string, 필수): 카테고리 제목
- `description` (string, 선택): 카테고리 설명
- `parent` (string, 선택): 상위 카테고리 sys_id
- `icon` (string, 선택): 카테고리 아이콘
- `active` (boolean, 기본값: true): 카테고리 활성화 여부
- `order` (integer, 선택): 카테고리 정렬 순서

**예시:**
```python
from servicenow_mcp.tools.catalog_tools import CreateCatalogCategoryParams, create_catalog_category

params = CreateCatalogCategoryParams(
    title="Cloud Services",
    description="Cloud-based services and resources",
    parent="parent_category_id",
    icon="cloud"
)
result = create_catalog_category(config, auth_manager, params)
```

### `update_catalog_category`

기존 서비스 카탈로그 카테고리를 업데이트합니다.

**매개변수:**
- `category_id` (string, 필수): 카테고리 ID 또는 sys_id
- `title` (string, 선택): 카테고리 제목
- `description` (string, 선택): 카테고리 설명
- `parent` (string, 선택): 상위 카테고리 sys_id
- `icon` (string, 선택): 카테고리 아이콘
- `active` (boolean, 선택): 카테고리 활성화 여부
- `order` (integer, 선택): 카테고리 정렬 순서

**예시:**
```python
from servicenow_mcp.tools.catalog_tools import UpdateCatalogCategoryParams, update_catalog_category

params = UpdateCatalogCategoryParams(
    category_id="category123",
    title="IT Equipment",
    description="Updated description for IT equipment"
)
result = update_catalog_category(config, auth_manager, params)
```

### `move_catalog_items`

카탈로그 항목을 다른 카테고리로 이동합니다.

**매개변수:**
- `item_ids` (문자열 목록, 필수): 이동할 카탈로그 항목 ID 목록
- `target_category_id` (string, 필수): 항목을 이동할 대상 카테고리 ID

**예시:**
```python
from servicenow_mcp.tools.catalog_tools import MoveCatalogItemsParams, move_catalog_items

params = MoveCatalogItemsParams(
    item_ids=["item1", "item2", "item3"],
    target_category_id="target_category_id"
)
result = move_catalog_items(config, auth_manager, params)
```

### `list_catalog_items`

사용 가능한 서비스 카탈로그 항목을 조회합니다.

**매개변수:**
- `limit` (int, 기본값: 10): 반환할 최대 항목 수
- `offset` (int, 기본값: 0): 페이지네이션 오프셋
- `category` (string, 선택): 카테고리별 필터
- `query` (string, 선택): 항목 검색어
- `active` (boolean, 기본값: true): 활성 항목만 반환할지 여부

**예시:**
```python
from servicenow_mcp.tools.catalog_tools import ListCatalogItemsParams, list_catalog_items

params = ListCatalogItemsParams(
    limit=5,
    category="hardware",
    query="laptop"
)
result = list_catalog_items(config, auth_manager, params)
```

### `get_catalog_item`

특정 카탈로그 항목의 상세 정보를 조회합니다.

**매개변수:**
- `item_id` (string, 필수): 카탈로그 항목 ID 또는 sys_id

**예시:**
```python
from servicenow_mcp.tools.catalog_tools import GetCatalogItemParams, get_catalog_item

params = GetCatalogItemParams(
    item_id="item123"
)
result = get_catalog_item(config, auth_manager, params)
```

## 리소스

ServiceNow 서비스 카탈로그에 접근하기 위한 리소스는 다음과 같습니다.

### `catalog://items`

서비스 카탈로그 항목을 조회합니다.

**예시:**
```
catalog://items
```

### `catalog://categories`

서비스 카탈로그 카테고리를 조회합니다.

**예시:**
```
catalog://categories
```

### `catalog://{item_id}`

ID로 특정 카탈로그 항목을 조회합니다.

**예시:**
```
catalog://item123
```

## Claude Desktop 연동

ServiceNow 서비스 카탈로그를 Claude Desktop에서 사용하려면:

1. Claude Desktop에서 ServiceNow MCP 서버를 설정합니다
2. Claude에게 서비스 카탈로그에 대해 질문합니다

**예시 프롬프트:**
- "Can you list the available service catalog categories in ServiceNow?"
- "Can you show me the available items in the ServiceNow service catalog?"
- "Can you list the catalog items in the Hardware category?"
- "Can you show me the details of the 'New Laptop' catalog item?"
- "Can you find catalog items related to 'software' in ServiceNow?"
- "Can you create a new category called 'Cloud Services' in the service catalog?"
- "Can you update the 'Hardware' category to rename it to 'IT Equipment'?"
- "Can you move the 'Virtual Machine' catalog item to the 'Cloud Services' category?"
- "Can you create a subcategory called 'Monitors' under the 'IT Equipment' category?"
- "Can you reorganize our catalog by moving all software items to the 'Software' category?"

## 예시 스크립트

### 연동 테스트

`examples/catalog_integration_test.py` 스크립트는 카탈로그 도구를 직접 사용하는 방법을 보여줍니다.

```bash
python examples/catalog_integration_test.py
```

### Claude Desktop 데모

`examples/claude_catalog_demo.py` 스크립트는 Claude Desktop에서 카탈로그 기능을 사용하는 방법을 보여줍니다.

```bash
python examples/claude_catalog_demo.py
```

## 데이터 모델

### CatalogItemModel

ServiceNow 카탈로그 항목을 나타냅니다.

**필드:**
- `sys_id` (string): 카탈로그 항목의 고유 식별자
- `name` (string): 카탈로그 항목 이름
- `short_description` (string, 선택): 카탈로그 항목의 간단한 설명
- `description` (string, 선택): 카탈로그 항목의 상세 설명
- `category` (string, 선택): 카탈로그 항목의 카테고리
- `price` (string, 선택): 카탈로그 항목의 가격
- `picture` (string, 선택): 카탈로그 항목의 이미지 URL
- `active` (boolean, 선택): 카탈로그 항목 활성화 여부
- `order` (integer, 선택): 카테고리 내 카탈로그 항목의 정렬 순서

### CatalogCategoryModel

ServiceNow 카탈로그 카테고리를 나타냅니다.

**필드:**
- `sys_id` (string): 카테고리의 고유 식별자
- `title` (string): 카테고리 제목
- `description` (string, 선택): 카테고리 설명
- `parent` (string, 선택): 상위 카테고리 ID
- `icon` (string, 선택): 카테고리 아이콘
- `active` (boolean, 선택): 카테고리 활성화 여부
- `order` (integer, 선택): 카테고리 정렬 순서

### CatalogItemVariableModel

ServiceNow 카탈로그 항목 변수를 나타냅니다.

**필드:**
- `sys_id` (string): 변수의 고유 식별자
- `name` (string): 변수 이름
- `label` (string): 변수 라벨
- `type` (string): 변수 타입
- `mandatory` (boolean, 선택): 필수 변수 여부
- `default_value` (string, 선택): 변수의 기본값
- `help_text` (string, 선택): 변수의 도움말 텍스트
- `order` (integer, 선택): 변수의 정렬 순서
