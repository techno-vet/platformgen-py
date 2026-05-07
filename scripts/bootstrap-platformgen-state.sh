#!/bin/bash
set -euo pipefail

STATE_DIR="${AUGER_HOME:-$HOME/.platformgen}"
SOURCE_DIR="${AUGER_MIGRATION_SOURCE:-$HOME/.auger}"

mkdir -p "$STATE_DIR"

if [ -d "$SOURCE_DIR" ]; then
    rsync -a --ignore-existing \
        --exclude 'venv' \
        --exclude '*.pid' \
        --exclude '*.sock' \
        --exclude 'daemon.log' \
        --exclude 'tray.log' \
        --exclude 'startup-progress.log' \
        --exclude 'icons' \
        --exclude '.copilot.lock' \
        --exclude '.session_id' \
        --exclude '.session_snapshot.json' \
        "$SOURCE_DIR/" "$STATE_DIR/"

    mkdir -p "$STATE_DIR/logs"

    for name in .session_id .session_snapshot.json; do
        if [ -e "$SOURCE_DIR/$name" ] || [ -L "$SOURCE_DIR/$name" ]; then
            rm -rf "$STATE_DIR/$name"
            ln -s "$SOURCE_DIR/$name" "$STATE_DIR/$name"
        fi
    done
fi

mkdir -p "$STATE_DIR/logs/chat_history"

if [ -d "$SOURCE_DIR/logs/chat_history" ] && [ ! -e "$STATE_DIR/logs/chat_history/conversations.jsonl" ]; then
    rsync -a "$SOURCE_DIR/logs/chat_history/" "$STATE_DIR/logs/chat_history/"
fi

if [ -L "$STATE_DIR/logs/chat_history" ]; then
    tmpdir="$(mktemp -d)"
    rsync -a "$STATE_DIR/logs/chat_history/" "$tmpdir/"
    rm -f "$STATE_DIR/logs/chat_history"
    mkdir -p "$STATE_DIR/logs/chat_history"
    rsync -a "$tmpdir/" "$STATE_DIR/logs/chat_history/"
    rm -rf "$tmpdir"
fi

if [ -e "$SOURCE_DIR/chat_history.jsonl" ] && [ ! -e "$STATE_DIR/chat_history.jsonl" ]; then
    cp "$SOURCE_DIR/chat_history.jsonl" "$STATE_DIR/chat_history.jsonl"
fi

if [ -L "$STATE_DIR/chat_history.jsonl" ]; then
    tmpfile="$(mktemp)"
    cat "$STATE_DIR/chat_history.jsonl" > "$tmpfile"
    rm -f "$STATE_DIR/chat_history.jsonl"
    cat "$tmpfile" > "$STATE_DIR/chat_history.jsonl"
    rm -f "$tmpfile"
fi
