import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  Button,
  Callout,
  DisclosureList,
  DisclosureRow,
  Field,
  SegmentedControl,
  SelectableThumb,
  Tab,
  TabList,
  TextInput,
  ToggleChip,
  buttonClass,
} from "@/components/ui";

describe("Button", () => {
  it("defaults to type=button so it never submits a form by accident", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toHaveAttribute("type", "button");
  });

  it("keeps a decorative icon out of the accessible name", () => {
    render(<Button icon={<svg data-testid="icon" />}>Generate</Button>);
    expect(screen.getByRole("button", { name: "Generate" })).toBeInTheDocument();
    expect(screen.getByTestId("icon").parentElement).toHaveAttribute("aria-hidden", "true");
  });

  it("does not fire while disabled", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Publish
      </Button>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("exposes its look for links", () => {
    expect(buttonClass({ variant: "primary", size: "sm" })).toContain("primary");
  });
});

describe("Callout", () => {
  it("renders the role the caller gives it, and none by default", () => {
    const { rerender } = render(<Callout tone="danger">Failed.</Callout>);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    rerender(
      <Callout tone="danger" role="alert">
        Failed.
      </Callout>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Failed.");
  });

  it("can be a list", () => {
    render(
      <Callout tone="warn" as="ul">
        <li>One</li>
      </Callout>,
    );
    expect(screen.getByRole("list")).toBeInTheDocument();
  });
});

describe("Field + TextInput", () => {
  it("associates the label, marks optional fields and hides the icon", () => {
    render(
      <Field label="Reference URL" htmlFor="ref" isOptional>
        <TextInput id="ref" icon={<svg data-testid="icon" />} />
      </Field>,
    );
    expect(screen.getByLabelText(/Reference URL/)).toHaveAttribute("id", "ref");
    expect(screen.getByText("(optional)")).toBeInTheDocument();
    expect(screen.getByTestId("icon").parentElement).toHaveAttribute("aria-hidden", "true");
  });
});

describe("TabList", () => {
  function Platforms() {
    const [active, setActive] = useState("facebook");
    return (
      <TabList label="Platform">
        {["facebook", "instagram"].map((name) => (
          <Tab key={name} isSelected={active === name} onClick={() => setActive(name)}>
            {name}
          </Tab>
        ))}
      </TabList>
    );
  }

  it("is one Tab stop and moves selection with the arrow keys", () => {
    render(<Platforms />);
    const facebook = screen.getByRole("tab", { name: "facebook" });
    const instagram = screen.getByRole("tab", { name: "instagram" });
    expect(facebook).toHaveAttribute("tabindex", "0");
    expect(instagram).toHaveAttribute("tabindex", "-1");

    facebook.focus();
    fireEvent.keyDown(facebook, { key: "ArrowRight" });
    expect(instagram).toHaveAttribute("aria-selected", "true");
    expect(instagram).toHaveFocus();

    fireEvent.keyDown(instagram, { key: "ArrowRight" });
    expect(facebook).toHaveAttribute("aria-selected", "true");
  });
});

describe("SegmentedControl", () => {
  const OPTIONS = [
    { value: "fast", label: "Fast", hint: "~5 s" },
    { value: "slow", label: "Slow", hint: "~45 s" },
  ] as const;

  it("is a radio group named by its visible label", () => {
    render(
      <SegmentedControl
        label="Writing speed"
        name="speed"
        value="fast"
        options={OPTIONS}
        onChange={() => {}}
      />,
    );
    const group = screen.getByRole("radiogroup", { name: "Writing speed" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Fast/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Slow/ })).not.toBeChecked();
    expect(screen.getByText("~45 s")).toBeInTheDocument();
  });

  it("reports the chosen value", () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl
        label="Writing speed"
        name="speed"
        value="fast"
        options={OPTIONS}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("radio", { name: /Slow/ }));
    expect(onChange).toHaveBeenCalledWith("slow");
  });
});

describe("ToggleChip", () => {
  it("is a checkbox labelled by its content", () => {
    const onChange = vi.fn();
    render(<ToggleChip checked={false} onChange={onChange}>Instagram</ToggleChip>);
    fireEvent.click(screen.getByRole("checkbox", { name: "Instagram" }));
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});

describe("DisclosureRow", () => {
  it("shows its body only when expanded and reports the state", () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <DisclosureList>
        <DisclosureRow summary="HLTAID011" isExpanded={false} onToggle={onToggle}>
          Offerings
        </DisclosureRow>
      </DisclosureList>,
    );
    const toggle = screen.getByRole("button", { name: "HLTAID011" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Offerings")).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledTimes(1);

    rerender(
      <DisclosureList>
        <DisclosureRow summary="HLTAID011" isExpanded onToggle={onToggle}>
          Offerings
        </DisclosureRow>
      </DisclosureList>,
    );
    expect(screen.getByText("Offerings")).toBeInTheDocument();
  });
});

describe("SelectableThumb", () => {
  it("is named by its label, not by its order badge", () => {
    render(
      <SelectableThumb src="/a.png" label="Graduation" isSelected order={2} onToggle={() => {}} />,
    );
    const thumb = screen.getByRole("button", { name: "Graduation" });
    expect(thumb).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("2")).toHaveAttribute("aria-hidden", "true");
  });

  it("shows no order while unselected", () => {
    render(
      <SelectableThumb src="/a.png" label="Graduation" isSelected={false} order={1} onToggle={() => {}} />,
    );
    expect(screen.queryByText("1")).not.toBeInTheDocument();
  });
});
