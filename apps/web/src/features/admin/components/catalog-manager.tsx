"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import * as adminApi from "@/features/admin/api/admin.api";
import { adminKeys } from "@/features/admin/query-keys";
import { CatalogTree, type CatalogTreeItem } from "@/features/catalog/components/catalog-tree";
import { SeoPreview } from "@/features/catalog/components/seo-preview";

interface CategoryDraft {
  id?: string;
  parentId: string | null;
  level: "category" | "subcategory";
  slug: string;
  name: string;
  description: string;
  seoTitle: string;
  seoDescription: string;
  active: boolean;
  version: number;
}

interface TopicDraft {
  id?: string;
  categoryId: string;
  slug: string;
  title: string;
  summary: string;
  suggestedDurationMs: number;
  difficulty: "beginner" | "intermediate" | "advanced";
  skillHints: string;
  seoTitle: string;
  seoDescription: string;
  active: boolean;
  version: number;
}

const newCategory = (): CategoryDraft => ({
  parentId: null,
  level: "category",
  slug: "",
  name: "",
  description: "",
  seoTitle: "",
  seoDescription: "",
  active: true,
  version: 1,
});

const newTopic = (categoryId: string): TopicDraft => ({
  categoryId,
  slug: "",
  title: "",
  summary: "",
  suggestedDurationMs: 60000,
  difficulty: "beginner",
  skillHints: "",
  seoTitle: "",
  seoDescription: "",
  active: true,
  version: 1,
});

export function CatalogManager() {
  const queryClient = useQueryClient();
  const tree = useQuery({
    queryKey: [...adminKeys.all, "catalog"],
    queryFn: adminApi.adminCatalogTree,
  });
  const [draft, setDraft] = useState(newCategory);
  const [topicDraft, setTopicDraft] = useState<TopicDraft | null>(null);
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: [...adminKeys.all, "catalog"] });
  const saveCategory = useMutation({
    mutationFn: async () => {
      const input = {
        parentId: draft.parentId,
        level: draft.level,
        slug: draft.slug,
        name: draft.name,
        description: draft.description || null,
        icon: null,
        sortOrder: 0,
        isActive: draft.active,
        seoTitle: draft.seoTitle || null,
        seoDescription: draft.seoDescription || null,
      };
      return draft.id
        ? adminApi.updateCategory(draft.id, { ...input, version: draft.version })
        : adminApi.createCategory(input);
    },
    onSuccess: invalidate,
  });
  const saveTopic = useMutation({
    mutationFn: async () => {
      if (topicDraft === null) throw new Error("A topic must be selected");
      const input = {
        categoryId: topicDraft.categoryId,
        slug: topicDraft.slug,
        title: topicDraft.title,
        summary: topicDraft.summary || null,
        suggestedDurationMs: topicDraft.suggestedDurationMs,
        difficulty: topicDraft.difficulty,
        skillHints: topicDraft.skillHints
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        isActive: topicDraft.active,
        sortOrder: 0,
        seoTitle: topicDraft.seoTitle || null,
        seoDescription: topicDraft.seoDescription || null,
      };
      return topicDraft.id
        ? adminApi.updateTopic(topicDraft.id, { ...input, version: topicDraft.version })
        : adminApi.createTopic(input);
    },
    onSuccess: async (topic) => {
      setTopicDraft({
        id: topic.id,
        categoryId: topic.categoryId,
        slug: topic.slug,
        title: topic.title,
        summary: topic.summary ?? "",
        suggestedDurationMs: topic.suggestedDurationMs,
        difficulty: topic.difficulty,
        skillHints: topic.skillHints.join(", "),
        seoTitle: topic.seoTitle ?? "",
        seoDescription: topic.seoDescription ?? "",
        active: topic.isActive,
        version: topic.version,
      });
      await invalidate();
    },
  });
  const reorder = useMutation({
    mutationFn: ({
      entityType,
      values,
    }: {
      entityType: "category" | "topic";
      values: readonly CatalogTreeItem[];
    }) =>
      adminApi.reorderCatalog({
        entityType,
        items: values.flatMap((item, index) =>
          item.version === undefined
            ? []
            : [{ id: item.id, sortOrder: index, version: item.version }],
        ),
      }),
    onSuccess: invalidate,
  });
  if (tree.isPending) return <p role="status">Loading catalog…</p>;
  if (tree.isError)
    return (
      <p role="alert" className="text-destructive">
        Catalog could not be loaded.
      </p>
    );
  const categories = tree.data.categories.flatMap((category) => [category, ...category.children]);
  const categoryItems: CatalogTreeItem[] = categories.map((category) => ({
    id: category.id,
    title: category.name,
    kind: category.level,
    active: category.isActive,
    version: category.version,
  }));
  const selectedTopics =
    draft.id === undefined ? [] : tree.data.topics.filter((topic) => topic.categoryId === draft.id);
  const topicItems: CatalogTreeItem[] = selectedTopics.map((topic) => ({
    id: topic.id,
    title: topic.title,
    kind: "topic",
    active: topic.isActive,
    version: topic.version,
  }));
  const selectCategory = (item: CatalogTreeItem) => {
    const category = categories.find((candidate) => candidate.id === item.id);
    if (category === undefined) return;
    setDraft({
      id: category.id,
      parentId: category.parentId,
      level: category.level,
      slug: category.slug,
      name: category.name,
      description: category.description ?? "",
      seoTitle: category.seoTitle ?? "",
      seoDescription: category.seoDescription ?? "",
      active: category.isActive,
      version: category.version,
    });
    setTopicDraft(category.level === "subcategory" ? newTopic(category.id) : null);
  };
  const selectTopic = (item: CatalogTreeItem) => {
    const topic = selectedTopics.find((candidate) => candidate.id === item.id);
    if (topic === undefined) return;
    setTopicDraft({
      id: topic.id,
      categoryId: topic.categoryId,
      slug: topic.slug,
      title: topic.title,
      summary: topic.summary ?? "",
      suggestedDurationMs: topic.suggestedDurationMs,
      difficulty: topic.difficulty,
      skillHints: topic.skillHints.join(", "),
      seoTitle: topic.seoTitle ?? "",
      seoDescription: topic.seoDescription ?? "",
      active: topic.isActive,
      version: topic.version,
    });
  };
  const firstParent = tree.data.categories[0]?.id ?? null;
  return (
    <div className="grid gap-8 xl:grid-cols-[22rem_1fr]">
      <div className="space-y-6">
        <div className="flex gap-2">
          <Button
            type="button"
            onClick={() => {
              setDraft(newCategory());
              setTopicDraft(null);
            }}
          >
            New category
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={firstParent === null}
            onClick={() => {
              setDraft({ ...newCategory(), level: "subcategory", parentId: firstParent });
              setTopicDraft(null);
            }}
          >
            New subcategory
          </Button>
        </div>
        <CatalogTree
          items={categoryItems}
          onSelect={selectCategory}
          onReorder={(values) => {
            reorder.mutate({ entityType: "category", values });
          }}
        />
        {draft.level === "subcategory" && draft.id ? (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Topics</h2>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setTopicDraft(newTopic(draft.id ?? ""));
                }}
              >
                New topic
              </Button>
            </div>
            {topicItems.length > 0 ? (
              <CatalogTree
                items={topicItems}
                onSelect={selectTopic}
                onReorder={(values) => {
                  reorder.mutate({ entityType: "topic", values });
                }}
              />
            ) : (
              <p className="text-sm text-muted-foreground">No topics in this subcategory.</p>
            )}
          </section>
        ) : null}
      </div>
      <div className="space-y-8">
        <form
          className="space-y-4 rounded-xl border bg-surface p-6"
          onSubmit={(event) => {
            event.preventDefault();
            saveCategory.mutate();
          }}
        >
          <h2 className="text-xl font-semibold">
            {draft.id ? "Edit catalog entry" : "Create catalog entry"}
          </h2>
          <div>
            <Label htmlFor="catalog-name">Name</Label>
            <Input
              id="catalog-name"
              required
              value={draft.name}
              onChange={(event) => {
                setDraft({ ...draft, name: event.target.value });
              }}
            />
          </div>
          <div>
            <Label htmlFor="catalog-slug">Slug</Label>
            <Input
              id="catalog-slug"
              required
              value={draft.slug}
              onChange={(event) => {
                setDraft({ ...draft, slug: event.target.value });
              }}
            />
            {draft.id ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Changing this slug creates a permanent redirect from the old path.
              </p>
            ) : null}
          </div>
          <div>
            <Label htmlFor="catalog-description">Description</Label>
            <Textarea
              id="catalog-description"
              value={draft.description}
              onChange={(event) => {
                setDraft({ ...draft, description: event.target.value });
              }}
            />
          </div>
          <div>
            <Label htmlFor="catalog-seo-title">SEO title</Label>
            <Input
              id="catalog-seo-title"
              value={draft.seoTitle}
              onChange={(event) => {
                setDraft({ ...draft, seoTitle: event.target.value });
              }}
            />
          </div>
          <div>
            <Label htmlFor="catalog-seo-description">SEO description</Label>
            <Textarea
              id="catalog-seo-description"
              value={draft.seoDescription}
              onChange={(event) => {
                setDraft({ ...draft, seoDescription: event.target.value });
              }}
            />
          </div>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={draft.active}
              onChange={(event) => {
                setDraft({ ...draft, active: event.target.checked });
              }}
            />{" "}
            Active
          </label>
          <SeoPreview
            title={draft.seoTitle}
            description={draft.seoDescription}
            path={`/explore/${draft.slug}`}
          />
          <Button type="submit" disabled={saveCategory.isPending}>
            Save entry
          </Button>
        </form>
        {topicDraft ? (
          <form
            className="space-y-4 rounded-xl border bg-surface p-6"
            onSubmit={(event) => {
              event.preventDefault();
              saveTopic.mutate();
            }}
          >
            <h2 className="text-xl font-semibold">
              {topicDraft.id ? "Edit topic" : "Create topic"}
            </h2>
            <div>
              <Label htmlFor="topic-title">Title</Label>
              <Input
                id="topic-title"
                required
                value={topicDraft.title}
                onChange={(event) => {
                  setTopicDraft({ ...topicDraft, title: event.target.value });
                }}
              />
            </div>
            <div>
              <Label htmlFor="topic-slug">Slug</Label>
              <Input
                id="topic-slug"
                required
                value={topicDraft.slug}
                onChange={(event) => {
                  setTopicDraft({ ...topicDraft, slug: event.target.value });
                }}
              />
              {topicDraft.id ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Changing this slug creates a permanent redirect from the old path.
                </p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="topic-summary">Summary</Label>
              <Textarea
                id="topic-summary"
                value={topicDraft.summary}
                onChange={(event) => {
                  setTopicDraft({ ...topicDraft, summary: event.target.value });
                }}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label htmlFor="topic-duration">Duration in milliseconds</Label>
                <Input
                  id="topic-duration"
                  type="number"
                  min={10000}
                  max={120000}
                  value={topicDraft.suggestedDurationMs}
                  onChange={(event) => {
                    setTopicDraft({
                      ...topicDraft,
                      suggestedDurationMs: Number(event.target.value),
                    });
                  }}
                />
              </div>
              <div>
                <Label htmlFor="topic-difficulty">Difficulty</Label>
                <select
                  id="topic-difficulty"
                  className="mt-1 h-9 w-full rounded-md border bg-surface px-3"
                  value={topicDraft.difficulty}
                  onChange={(event) => {
                    setTopicDraft({
                      ...topicDraft,
                      difficulty: event.target.value as TopicDraft["difficulty"],
                    });
                  }}
                >
                  <option value="beginner">Beginner</option>
                  <option value="intermediate">Intermediate</option>
                  <option value="advanced">Advanced</option>
                </select>
              </div>
            </div>
            <div>
              <Label htmlFor="topic-skills">Skill hints, separated by commas</Label>
              <Input
                id="topic-skills"
                value={topicDraft.skillHints}
                onChange={(event) => {
                  setTopicDraft({ ...topicDraft, skillHints: event.target.value });
                }}
              />
            </div>
            <div>
              <Label htmlFor="topic-seo-title">SEO title</Label>
              <Input
                id="topic-seo-title"
                value={topicDraft.seoTitle}
                onChange={(event) => {
                  setTopicDraft({ ...topicDraft, seoTitle: event.target.value });
                }}
              />
            </div>
            <div>
              <Label htmlFor="topic-seo-description">SEO description</Label>
              <Textarea
                id="topic-seo-description"
                value={topicDraft.seoDescription}
                onChange={(event) => {
                  setTopicDraft({ ...topicDraft, seoDescription: event.target.value });
                }}
              />
            </div>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={topicDraft.active}
                onChange={(event) => {
                  setTopicDraft({ ...topicDraft, active: event.target.checked });
                }}
              />{" "}
              Active
            </label>
            <SeoPreview
              title={topicDraft.seoTitle}
              description={topicDraft.seoDescription}
              path={`/explore/${draft.slug}/${topicDraft.slug}`}
            />
            <Button type="submit" disabled={saveTopic.isPending}>
              Save topic
            </Button>
          </form>
        ) : null}
      </div>
    </div>
  );
}
