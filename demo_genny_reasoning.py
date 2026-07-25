#!/usr/bin/env python3
"""Demo of Ask Genny response display with reasoning animations and styling.

Run this to see:
1. Inline reasoning callouts with colored backgrounds
2. Thinking spinner animation
3. Double-spacing fix (live vs. history parity)
4. Token counter display
"""

import tkinter as tk
from tkinter import ttk
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from auger.ui.markdown_widget_with_reasoning import MarkdownWidgetWithReasoning
from auger.ui.reasoning_animator import TokenCounter


def demo_response_with_reasoning():
    """Demo showing live response with inline reasoning callouts."""
    root = tk.Tk()
    root.title("Ask Genny UI Demo - Reasoning Animations")
    root.geometry("900x700")
    root.configure(bg='#1e1e1e')
    
    # Header
    header = tk.Frame(root, bg='#007acc', height=40)
    header.pack(fill=tk.X, side=tk.TOP)
    header.pack_propagate(False)
    
    tk.Label(
        header,
        text="  [AI]  Ask Genny - Response Display with Reasoning",
        font=('Segoe UI', 11, 'bold'),
        fg='white',
        bg='#007acc'
    ).pack(side=tk.LEFT, padx=10)
    
    # Token counter
    token_label = tk.Label(
        header,
        text="📊 0 tokens | 0.0 t/s",
        font=('Segoe UI', 9),
        fg='#d0d0d0',
        bg='#007acc'
    )
    token_label.pack(side=tk.RIGHT, padx=10)
    token_counter = TokenCounter(token_label)
    
    # Response area with scrollbar
    response_frame = tk.Frame(root, bg='#1a1a2e')
    response_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    scrollbar = tk.Scrollbar(response_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    response = MarkdownWidgetWithReasoning(response_frame, yscrollcommand=scrollbar.set)
    response.pack(fill=tk.BOTH, expand=True)
    scrollbar.config(command=response.yview)
    
    # Demo button
    demo_frame = tk.Frame(root, bg='#252526')
    demo_frame.pack(fill=tk.X, padx=5, pady=5)
    
    def run_demo():
        """Show demo response with reasoning."""
        response.clear()
        
        # User prompt
        response.append_markdown("### 💬 You\n")
        response.append_markdown("How do I optimize database queries?\n\n")
        
        # Assistant response with reasoning
        response.append_markdown("### 🤖 Claude\n\n")
        
        # Reasoning block
        response.append_reasoning(
            "Understanding the Question",
            """To optimize database queries effectively, I need to consider:
- Query structure and execution plans
- Index usage and statistics
- Data volume and table design
- Connection pooling and caching strategies"""
        )
        
        # Main response
        response.append_markdown("""Here are the key strategies for optimizing database queries:

**1. Use Proper Indexing**
- Index on columns used in WHERE clauses
- Consider composite indexes for multi-column filters
- Avoid over-indexing (slows writes)

```sql
CREATE INDEX idx_user_email ON users(email);
CREATE INDEX idx_order_date_user ON orders(created_at, user_id);
```

**2. Optimize Query Structure**
- Use EXPLAIN/EXPLAIN ANALYZE to review execution plans
- Avoid SELECT * — specify only needed columns
- Use LIMIT for testing large result sets
- Join tables efficiently (prefer INNER joins)

**3. Connection Pooling**
- Use libraries like pgbouncer or HikariCP
- Maintain a pool of 10-20 connections per worker
- Reduces handshake overhead by 60-80%

**4. Caching Strategy**
- Cache at application level (Redis, Memcached)
- Cache query results for read-heavy operations
- Invalidate strategically to keep data fresh

**5. Database-Level Tuning**
- Analyze table statistics regularly (ANALYZE)
- Set appropriate work_mem for PostgreSQL
- Enable query parallelization for large tables
""")
        
        # Another reasoning block
        response.append_reasoning(
            "Implementation Approach",
            """Start with:
1. Profile queries (find slow ones) → 1 hour
2. Add indexes on hot columns → 30 mins
3. Implement caching for top 5 queries → 2 hours
4. Monitor improvements with EXPLAIN ANALYZE"""
        )
        
        response.append_markdown("\n**Start with profiling** — most gains come from index optimization.")
        
        # Simulate token count update
        root.after(500, lambda: token_counter.update(145, 380))
    
    tk.Button(
        demo_frame,
        text="▶ Run Demo",
        command=run_demo,
        bg='#007acc',
        fg='white',
        font=('Segoe UI', 10, 'bold'),
        relief=tk.FLAT,
        cursor='hand2',
        padx=15, pady=5
    ).pack(side=tk.LEFT, padx=5)
    
    tk.Label(
        demo_frame,
        text="Shows: Inline reasoning callouts + proper spacing + token counter",
        font=('Segoe UI', 9),
        fg='#a0a0a0',
        bg='#252526'
    ).pack(side=tk.LEFT, padx=10)
    
    # Run demo on startup
    root.after(100, run_demo)
    
    root.mainloop()


if __name__ == '__main__':
    demo_response_with_reasoning()
