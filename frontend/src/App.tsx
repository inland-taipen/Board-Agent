import { useCallback, useEffect, useState } from "react";

import { api, session, type Board, type SessionUser } from "./api";
import SignIn from "./pages/SignIn";
import Boards from "./pages/Boards";
import PackWorkspace from "./pages/PackWorkspace";
import BriefingView from "./pages/BriefingView";
import ActionRegister from "./pages/ActionRegister";
import People from "./pages/People";

type View =
  | { name: "boards" }
  | { name: "packs"; board: Board }
  | { name: "briefing"; board: Board; briefingId: string }
  | { name: "actions"; board: Board }
  | { name: "people"; board: Board };

export default function App() {
  const [user, setUser] = useState<SessionUser | null>(session.user);
  const [view, setView] = useState<View>({ name: "boards" });
  const [boards, setBoards] = useState<Board[]>([]);
  const [error, setError] = useState("");

  const loadBoards = useCallback(async () => {
    try {
      const result = await api.boards();
      setBoards(result);
      // A user with exactly one board should not have to pick it every time.
      if (result.length === 1) {
        setView((current) =>
          current.name === "boards" ? { name: "packs", board: result[0] } : current,
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    if (user) void loadBoards();
  }, [user, loadBoards]);

  if (!user) {
    return (
      <SignIn
        onSignedIn={(signedIn) => {
          setUser(signedIn);
          setView({ name: "boards" });
        }}
      />
    );
  }

  const board = view.name === "boards" ? null : view.board;

  const signOut = () => {
    session.clear();
    setUser(null);
    setBoards([]);
    setView({ name: "boards" });
  };

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          BoardLens AI<span>Board Intelligence Agent</span>
        </div>

        {board && (
          <nav>
            <button
              aria-current={view.name === "packs" || view.name === "briefing"}
              onClick={() => setView({ name: "packs", board })}
            >
              Meetings
            </button>
            <button
              aria-current={view.name === "actions"}
              onClick={() => setView({ name: "actions", board })}
            >
              Action register
            </button>
            {user.role === "admin" && (
              <button
                aria-current={view.name === "people"}
                onClick={() => setView({ name: "people", board })}
              >
                People
              </button>
            )}
            {boards.length > 1 && (
              <button onClick={() => setView({ name: "boards" })}>Change board</button>
            )}
          </nav>
        )}

        <div className="spacer" />
        <div className="who">
          {user.display_name} · {user.role}
        </div>
        <button className="signout" onClick={signOut}>
          Sign out
        </button>
      </header>

      <main>
        {error && <div className="banner error page">{error}</div>}

        {view.name === "boards" && (
          <Boards
            boards={boards}
            canCreate={user.role === "admin"}
            onSelect={(selected) => setView({ name: "packs", board: selected })}
            onCreated={loadBoards}
          />
        )}

        {view.name === "packs" && (
          <PackWorkspace
            board={view.board}
            role={user.role}
            onOpenBriefing={(briefingId) =>
              setView({ name: "briefing", board: view.board, briefingId })
            }
          />
        )}

        {view.name === "briefing" && (
          <BriefingView
            briefingId={view.briefingId}
            onBack={() => setView({ name: "packs", board: view.board })}
          />
        )}

        {view.name === "people" && <People board={view.board} />}

        {view.name === "actions" && (
          <ActionRegister board={view.board} canEdit={user.role !== "director"} />
        )}
      </main>
    </div>
  );
}
