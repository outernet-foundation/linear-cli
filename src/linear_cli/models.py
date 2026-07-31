from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, RootModel


class LinearModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class PageInfo(LinearModel):
    has_next_page: bool = Field(alias="hasNextPage")
    end_cursor: str | None = Field(default=None, alias="endCursor")


class Connection[NodeT](LinearModel):
    page_info: PageInfo = Field(alias="pageInfo")
    nodes: list[NodeT]


class NodeList[NodeT](LinearModel):
    nodes: list[NodeT]


class TeamNode(LinearModel):
    id: str
    key: str
    name: str


class IssueStateNode(LinearModel):
    name: str
    type: str


class IssueLabelName(LinearModel):
    name: str


class ProjectRef(LinearModel):
    id: str
    name: str


class IssueListNode(LinearModel):
    id: str
    identifier: str
    title: str
    description: str | None = None
    url: str
    created_at: str = Field(alias="createdAt")
    archived_at: str | None = Field(default=None, alias="archivedAt")
    state: IssueStateNode
    labels: NodeList[IssueLabelName]
    project: ProjectRef | None = None


class ProjectListNode(LinearModel):
    id: str
    name: str
    url: str
    state: str


class CommentUserNode(LinearModel):
    name: str


class IssueSnapshotCommentNode(LinearModel):
    body: str | None = None
    created_at: str = Field(alias="createdAt")
    user: CommentUserNode | None = None


class IssueSnapshotNode(LinearModel):
    id: str
    identifier: str
    title: str
    description: str | None = None
    priority: int = 0
    archived_at: str | None = Field(default=None, alias="archivedAt")
    state: IssueStateNode
    team: TeamNode | None = None
    project: ProjectRef | None = None
    labels: NodeList[IssueLabelName]
    comments: NodeList[IssueSnapshotCommentNode]


class WorkflowStateNode(LinearModel):
    id: str
    name: str
    type: str


class LabelParent(LinearModel):
    id: str


class LabelNode(LinearModel):
    id: str
    name: str
    color: str | None = None
    is_group: bool = Field(default=False, alias="isGroup")
    parent: LabelParent | None = None


class TeamsData(LinearModel):
    teams: NodeList[TeamNode]


class IssuesData(LinearModel):
    issues: Connection[IssueListNode]


class ProjectsData(LinearModel):
    projects: Connection[ProjectListNode]


class IssueSnapshotData(LinearModel):
    issues: Connection[IssueSnapshotNode]


class WorkflowStatesData(LinearModel):
    workflow_states: NodeList[WorkflowStateNode] = Field(alias="workflowStates")


class LabelsData(LinearModel):
    issue_labels: NodeList[LabelNode] = Field(alias="issueLabels")


class ResponsePayload(RootModel[dict[str, object]]):
    root: dict[str, object]
