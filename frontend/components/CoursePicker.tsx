"use client";

// Searchable course picker backed by GET /api/courses (requirement 5).

import { useEffect, useRef, useState } from "react";

import { fetchCourses } from "@/lib/api";
import type { Course } from "@/types/course";
import styles from "./CoursePicker.module.css";

const SEARCH_DEBOUNCE_MS = 250;

interface CoursePickerProps {
  selected: Course | null;
  onSelect: (course: Course | null) => void;
}

export default function CoursePicker({ selected, onSelect }: CoursePickerProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Course[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (!isOpen) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      fetchCourses(query ? { search: query } : undefined)
        .then((courses) => {
          setResults(courses);
          setError(null);
        })
        .catch(() => setError("Could not load courses."));
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer.current);
  }, [query, isOpen]);

  if (selected) {
    return (
      <div className={styles.selected}>
        <div>
          <p className={styles.selectedTitle}>{selected.title}</p>
          <p className={styles.selectedMeta}>
            {selected.course_code}
            {selected.category ? ` · ${selected.category}` : ""}
            {selected.is_accredited ? " · Accredited" : ""}
          </p>
        </div>
        <button
          type="button"
          className={styles.clear}
          onClick={() => onSelect(null)}
        >
          Clear
        </button>
      </div>
    );
  }

  return (
    <div className={styles.picker}>
      <input
        type="search"
        className={styles.input}
        placeholder="Search the course catalog…"
        value={query}
        onFocus={() => setIsOpen(true)}
        onChange={(event) => setQuery(event.target.value)}
        aria-label="Search courses"
      />
      {error ? <p className={styles.error}>{error}</p> : null}
      {isOpen && results.length > 0 ? (
        <ul className={styles.results}>
          {results.slice(0, 8).map((course) => (
            <li key={course.id}>
              <button
                type="button"
                className={styles.result}
                onClick={() => {
                  onSelect(course);
                  setIsOpen(false);
                }}
              >
                <span className={styles.resultTitle}>{course.title}</span>
                <span className={styles.resultMeta}>
                  {course.course_code}
                  {course.category ? ` · ${course.category}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {isOpen && !error && results.length === 0 ? (
        <p className={styles.empty}>
          No courses found — run a catalog sync first, or use a free topic.
        </p>
      ) : null}
    </div>
  );
}
