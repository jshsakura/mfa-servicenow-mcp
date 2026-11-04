# 변경 관리

도구 하나, `manage_change`로 변경 요청(`change_request`), 변경 태스크, 승인 단계를 다룹니다.

| 패키지 | 액션 |
|---|---|
| `platform_developer` | 승인(approve)과 반려(reject)를 뺀 모든 액션 |
| `full` | 모든 액션 |

쓰기 액션은 이 서버의 다른 쓰기와 마찬가지로 `confirm='approve'`가 필요합니다. 길거나 조건이 복잡한 목록은 `table=change_request`로 `sn_query`를 써도 됩니다.

## 액션

| 액션 | 필수 | 선택 |
|---|---|---|
| `action="get"` | 한 건이면 `change_id`, 목록이면 없음 | `limit`, `offset`, `timeframe`, `query`, `state`, `type`, `category`, `assignment_group`, `count_only` |
| `action="create"` | `short_description`, `type` | `description`, `risk`, `impact`, `category`, `requested_by`, `assignment_group`, `start_date`, `end_date` |
| `action="update"` | `change_id`와 필드 하나 이상 | `short_description`, `description`, `state`, `risk`, `impact`, `category`, `assignment_group`, `start_date`, `end_date`, `work_notes` |
| `action="add_task"` | `change_id`, `task_short_description` | `task_description`, `task_assigned_to`, `task_planned_start_date`, `task_planned_end_date` |
| `action="submit"` | `change_id` | `state`(기본 Assess), `work_notes`(승인 요청 코멘트) |
| `action="approve"` | `change_id` | `approver_id`, `state`(기본 Implement), `work_notes`(코멘트) |
| `action="reject"` | `change_id`, `work_notes`(반려 사유) | `approver_id`, `state`(기본 Canceled) |

## 승인

- `action="submit"`은 변경 요청을 목표 상태로 옮기고, requested 상태의 승인 레코드를 만듭니다.
- `action="approve"`와 `action="reject"`는 `approver_id`(sys_id 또는 이름)의 승인 레코드에 적용합니다. 없으면 아직 대기 중인 첫 레코드에 적용합니다. 그다음 변경 요청을 목표 상태로 옮깁니다.
- submit과 approve는 다른 사람이 이어서 처리하는 변경을 움직이므로 `confirm_publish='approve'`도 필요합니다.

## 선택지 값

`state`, `type`, `risk`, `impact`에는 단어가 아니라 코드가 저장됩니다. 예를 들어 `state`의 -4는 Assess, -1은 Implement입니다. 코드나 라벨 중 하나를 넘기면 됩니다. 쓰기 전에 그 인스턴스의 선택지 목록(`sys_choice`)과 대조하고, 목록에 없는 값은 거절하면서 사용할 수 있는 값을 모두 알려 줍니다.

approve와 reject는 승인 레코드를 건드리기 전에 목표 상태부터 확인합니다. 그래서 잘못된 상태 때문에 승인만 처리되고 변경 요청은 그대로 남는 일이 없습니다.

## 미리보기

모든 쓰기 액션에 `dry_run=true`를 줄 수 있습니다.

- `action="update"`는 필드별 차이를 보여 줍니다.
- `action="approve"`와 `action="reject"`는 바뀔 승인 레코드와 변경 요청 상태를 보여 줍니다.
- 그 밖의 쓰기 액션은 보낼 요청을 그대로 `would_send`로 돌려줍니다.

어느 경우든 아무것도 쓰지 않습니다.

## 프롬프트 예시

- "내일 밤 보안 패치 적용을 위한 서버 점검 변경 요청을 만들어 줘."
- "서버 점검 변경에 사전 점검 태스크를 추가해 줘."
- "서버 점검 변경을 승인 요청해 줘."
- "DB 업그레이드 변경을 승인해 줘. 코멘트: 구현 계획이 꼼꼼함."
- "네트워크 변경을 반려해 줘. 사유: 테스트 부족."
- "이번 주에 예정된 긴급 변경을 모두 보여 줘."
