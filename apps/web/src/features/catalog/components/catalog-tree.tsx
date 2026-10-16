"use client";

import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVerticalIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

export interface CatalogTreeItem {
  id: string;
  title: string;
  kind: "category" | "subcategory" | "topic";
  active: boolean;
  version?: number;
}

export const reorderCatalogItems = (
  items: readonly CatalogTreeItem[],
  activeId: string,
  overId: string,
): CatalogTreeItem[] => {
  const from = items.findIndex((item) => item.id === activeId);
  const to = items.findIndex((item) => item.id === overId);
  return from < 0 || to < 0 || from === to ? [...items] : arrayMove([...items], from, to);
};

function SortableCatalogItem({
  item,
  onSelect,
}: {
  item: CatalogTreeItem;
  onSelect: (item: CatalogTreeItem) => void;
}) {
  const sortable = useSortable({ id: item.id });
  return renderSortableCatalogItem(sortable, item, onSelect);
}

function renderSortableCatalogItem(
  sortable: ReturnType<typeof useSortable>,
  item: CatalogTreeItem,
  onSelect: (item: CatalogTreeItem) => void,
) {
  return (
    <li
      ref={sortable.setNodeRef}
      style={{
        transform: CSS.Transform.toString(sortable.transform),
        transition: sortable.transition,
      }}
      className="flex items-center gap-2 rounded-lg border bg-surface p-2"
    >
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={`Reorder ${item.title}`}
        {...sortable.attributes}
        {...sortable.listeners}
      >
        <GripVerticalIcon aria-hidden="true" />
      </Button>
      <button
        type="button"
        className="flex flex-1 items-center justify-between rounded-md px-2 py-1 text-left focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
        onClick={() => {
          onSelect(item);
        }}
      >
        <span>{item.title}</span>
        <span className="text-xs text-muted-foreground">{item.active ? "Active" : "Inactive"}</span>
      </button>
    </li>
  );
}

interface CatalogTreeProps {
  items: readonly CatalogTreeItem[];
  onReorder: (items: readonly CatalogTreeItem[]) => void;
  onSelect: (item: CatalogTreeItem) => void;
}

export function CatalogTree({ items: initialItems, onReorder, onSelect }: CatalogTreeProps) {
  const [items, setItems] = useState([...initialItems]);
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (over === null) {
      return;
    }
    const reordered = reorderCatalogItems(items, String(active.id), String(over.id));
    setItems(reordered);
    onReorder(reordered);
  };
  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <SortableContext items={items.map((item) => item.id)} strategy={verticalListSortingStrategy}>
        <ul aria-label="Catalog hierarchy" className="space-y-2">
          {items.map((item) => (
            <SortableCatalogItem key={item.id} item={item} onSelect={onSelect} />
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  );
}
