from bookmarks.data.model import Bookmark
from sqlalchemy.orm import Session


class BookmarkRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_bookmarks_by_document(self, user_id: str, document_id: str) -> list[Bookmark]:
        return (
            self.db.query(Bookmark)
            .filter(
                Bookmark.user_id == user_id,
                Bookmark.document_id == document_id,
                Bookmark.is_deleted == False,
            )
            .order_by(Bookmark.content_id)
            .all()
        )

    def get_bookmark_by_id(self, bookmark_id: str) -> Bookmark | None:
        return (
            self.db.query(Bookmark)
            .filter(Bookmark.bookmark_id == bookmark_id, Bookmark.is_deleted == False)
            .first()
        )

    def create_bookmark(self, bookmark: Bookmark) -> Bookmark:
        self.db.add(bookmark)
        self.db.commit()
        self.db.refresh(bookmark)
        return bookmark

    def update_bookmark(self, bookmark: Bookmark) -> Bookmark:
        self.db.commit()
        self.db.refresh(bookmark)
        return bookmark

    def batch_update_bookmarks(self, bookmarks: list[Bookmark]) -> list[Bookmark]:
        self.db.commit()
        for bookmark in bookmarks:
            self.db.refresh(bookmark)
        return bookmarks

    def delete_bookmark(self, bookmark: Bookmark) -> bool:
        bookmark.is_deleted = True
        self.db.commit()
        return True
