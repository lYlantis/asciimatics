from __future__ import division
from __future__ import absolute_import
from __future__ import print_function
from builtins import object
from future.utils import with_metaclass
from abc import ABCMeta, abstractmethod
from asciimatics.effects import Effect
from asciimatics.event import KeyboardEvent
from asciimatics.renderers import Box
from asciimatics.screen import Screen, Canvas


class Frame(Effect):
    """
    A Frame is a special Effect for controlling and displaying Widgets.  Widgets
    are GUI elements that can be used to create an application.
    """

    # Colour palette for the widgets within te Frame.
    palette = {
        "background": (Screen.COLOUR_WHITE, 0, Screen.COLOUR_BLUE),
        "label": (Screen.COLOUR_WHITE, Screen.A_BOLD, Screen.COLOUR_BLUE),
        "borders": (Screen.COLOUR_BLACK, Screen.A_BOLD, Screen.COLOUR_BLUE),
        "edit_text": (Screen.COLOUR_WHITE, 0, Screen.COLOUR_CYAN),
        "field": (Screen.COLOUR_WHITE, 0, Screen.COLOUR_BLUE),
        "selected_field": (Screen.COLOUR_WHITE, Screen.A_BOLD, Screen.COLOUR_BLUE),
    }

    def __init__(self, screen, height, width):
        """
        :param screen: The Screen that owns this Frame.
        :param width: The desired width of the Frame.
        :param height: The desired height of the Frame.
        """
        super(Frame, self).__init__()
        self._focus = 0
        self._layouts = []
        self._canvas = Canvas(screen, height, width)

    def add_layout(self, layout):
        """
        Add a Layout to the Frame.

        :param layout: The Layout to be added.
        """
        layout.register_frame(self)
        self._layouts.append(layout)

    def fix(self):
        """
        Fix the layouts and calculate the locations of all the widgets.  This
        should be called once all Layouts have been added to the Frame and all
        widgets added to the Layouts.
        """
        y = 0
        for layout in self._layouts:
            y = layout.fix(y)
        self._layouts[self._focus].focus(force_first=True)
        self._clear()

    def _clear(self):
        """
        Clear the current canvas.
        """
        # It's orders of magnitude faster to reset with a print like this
        # instead of recreating the screen buffers.
        (colour, attr, bg) = self.palette["background"]
        # TODO: Fix internal use of buffer height.
        for y in range(self._canvas._buffer_height):
            self._canvas.print_at(
                " " * self._canvas.width, 0, y, colour, attr, bg)

    def _update(self, frame_no):
        # Update all the widgets and then push to the screen.
        for layout in self._layouts:
            layout.update(frame_no)
        self._canvas.refresh()
        self._clear()

    @property
    def stop_frame(self):
        # Widgets have no defined end - always return -1.
        return -1

    @property
    def canvas(self):
        """
        The Canvas that backs this Frame.
        """
        return self._canvas

    def reset(self):
        self._canvas.reset()
        for layout in self._layouts:
            layout.reset()

    def process_event(self, event):
        # Give the current widget in focus first chance to process the event.
        event = self._layouts[self._focus].process_event(event)

        # If the underlying widgets did not process the event, try processing
        # it now.
        if event is not None:
            if isinstance(event, KeyboardEvent):
                if event.key_code == Screen.KEY_TAB:
                    # Move on to next widget.
                    self._layouts[self._focus].blur()
                    self._focus += 1
                    if self._focus >= len(self._layouts):
                        self._focus = 0
                    self._layouts[self._focus].focus(force_first=True)
                    event = None
                elif event.key_code == Screen.KEY_BACK_TAB:
                    # Move on to previous widget.
                    self._layouts[self._focus].blur()
                    self._focus -= 1
                    if self._focus < 0:
                        self._focus = len(self._layouts) - 1
                    self._layouts[self._focus].focus(force_last=True)
                    event = None
        return event


class Layout(object):
    """
    Widget layout handler.  All Widgets must be contained within a Layout within
    a Frame.  The Layout class is responsible for deciding the exact size and
    location of the widgets.  The logic uses similar ideas as used in modern
    web frameworks and is as follows.

    1.  The Frame owns one or more Layouts.  The Layouts stack one above each
        other when displayed - i.e. the first Layout in the Frame is above the
        second, etc.
    2.  Each Layout defines the horizontal constraints by defining columns
        as a percentage of the full canvas width.
    3.  The Widgets are assigned a column within the Layout that owns them.
    4.  The Layout then decides the exact size and location to make the
        Widget best fit the canvas as constrained by the above.
    """

    def __init__(self, columns):
        """
        :param columns: A list of numbers specifying the width of each column
                        in this layout.

        The Layout will automatically normalize the units used for the columns,
        e.g. converting [2, 6, 2] to [20%, 60%, 20%] of the available canvas.
        """
        total_size = sum(columns)
        self._column_sizes = [x / total_size for x in columns]
        self._columns = [[] for _ in columns]
        self._frame = None
        self._has_focus = False
        self._live_col = 0
        self._live_widget = -1

    def register_frame(self, frame):
        """
        Register the Frame that owns this Widget.

        :param frame: The owning Frame.
        """
        self._frame = frame
        for column in self._columns:
            for widget in column:
                widget.register_frame(self._frame)

    def add_widget(self, widget, column=0):
        """
        Add a widget to this Layout.

        :param widget: The widget to be added.
        :param column: The column within the widget for this widget.  Defaults
                       to zero.
        """
        self._columns[column].append(widget)
        widget.register_frame(self._frame)

    def focus(self, force_first=False, force_last=False):
        """
        Call this to give this Layout the input focus.

        :param force_first: Optional parameter to force focus to first widget.
        :param force_last: Optional parameter to force focus to last widget.
        """
        self._has_focus = True
        if force_first:
            self._live_col = 0
            self._live_widget = -1
            self._find_next_widget(1)
        elif force_last:
            self._live_col = len(self._columns) - 1
            self._live_widget = len(self._columns[self._live_col])
            self._find_next_widget(-1)
        self._columns[self._live_col][self._live_widget].focus()

    def blur(self):
        """
        Call this to give take the input focus from this Layout.
        """
        self._has_focus = False
        self._columns[self._live_col][self._live_widget].blur()

    def fix(self, start_y):
        """
        Fix the location and size of all the Widgets in this Layout.

        :param start_y: The start line for the Layout.
        :returns: The next line to be used for any further Layouts.
        """
        x = 0
        max_y = start_y
        for i, column in enumerate(self._columns):
            # For each column determine if we need a tab offset for labels.
            # Only allow labels to take up 1/3 of the column.
            if len(column) > 0:
                offset = max([0 if w.label is None else len(w.label) + 1
                              for w in column])
            else:
                offset = 0
            offset = int(min(offset,
                         self._frame.canvas.width * self._column_sizes[i] // 3))

            # Now go through each widget getting them to resize to the required
            # width and label offset.
            y = start_y
            w = int(self._frame.canvas.width * self._column_sizes[i])
            for widget in column:
                h = widget.required_height(offset, w)
                widget.set_layout(x, y, offset, w, h)
                y += h
            max_y = max(max_y, y)
            x += w
        return max_y

    def _find_next_widget(self, direction, stay_in_col=False):
        """
        Find the next widget to get the focus, stopping at the start/end of the
        list if hit.

        :param direction: The direction to move through the widgets.
        :param stay_in_col: Whether to limit search to current column.
        """
        current_widget = self._live_widget
        while 0 <= self._live_col < len(self._columns):
            self._live_widget += direction
            while 0 <= self._live_widget < len(self._columns[self._live_col]):
                if self._columns[self._live_col][self._live_widget].is_tab_stop:
                    break
                self._live_widget += direction
            if (0 <= self._live_widget < len(self._columns[self._live_col]) and
                    self._columns[
                        self._live_col][self._live_widget].is_tab_stop):
                break
            if stay_in_col:
                # Don't move to another column - just stay where we are.
                self._live_widget = current_widget
                break
            else:
                self._live_col += direction
                self._live_widget = \
                    -1 if direction > 0 else len(self._columns[self._live_col])

    def process_event(self, event):
        """
        Process any input event.

        :param event: The event that was triggered.
        :returns: None if the Effect processed the event, else the original
                  event.
        """
        # Give the active widget the first refusal for this event.
        event = self._columns[
            self._live_col][self._live_widget].process_event(event)

        # Check for any movement keys if the widget refused them.
        if event is not None:
            if isinstance(event, KeyboardEvent):
                if event.key_code == Screen.KEY_TAB:
                    # Move on to next widget, unless it is the last in the
                    # Layout.
                    self._columns[self._live_col][self._live_widget].blur()
                    self._find_next_widget(1)
                    if self._live_col >= len(self._columns):
                        self._live_col = 0
                        self._live_widget = -1
                        self._find_next_widget(1)
                        return event

                    # If we got here, we still should have the focus.
                    self._columns[self._live_col][self._live_widget].focus()
                    event = None
                elif event.key_code == Screen.KEY_BACK_TAB:
                    # Move on to previous widget, unless it is the first in the
                    # Layout.
                    self._columns[self._live_col][self._live_widget].blur()
                    self._find_next_widget(-1)
                    if self._live_col < 0:
                        self._live_col = len(self._columns) - 1
                        self._live_widget = len(self._columns[self._live_col])
                        self._find_next_widget(-1)
                        return event

                    # If we got here, we still should have the focus.
                    self._columns[self._live_col][self._live_widget].focus()
                    event = None
                elif event.key_code == Screen.KEY_DOWN:
                    # Move on to next widget in this column
                    self._columns[self._live_col][self._live_widget].blur()
                    self._find_next_widget(1, stay_in_col=True)
                    self._columns[self._live_col][self._live_widget].focus()
                    event = None
                elif event.key_code == Screen.KEY_UP:
                    # Move on to previous widget, unless it is the first in the
                    # Layout.
                    self._columns[self._live_col][self._live_widget].blur()
                    self._find_next_widget(-1, stay_in_col=True)
                    self._columns[self._live_col][self._live_widget].focus()
                    event = None
        return event

    def update(self, frame_no):
        """
        Redraw the widgets inside this Layout.

        :param frame_no: The current frame to be drawn.
        """
        for column in self._columns:
            for widget in column:
                widget.update(frame_no)

    def reset(self):
        """
        Reset this Layout and the Widgets it contains.
        """
        # Reset all the widgets
        for column in self._columns:
            for widget in column:
                widget.reset()

        # Find the focus for the first widget
        self._live_widget = -1
        self._find_next_widget(1)


class Widget(with_metaclass(ABCMeta, object)):
    """
    A Widget is a re-usable component that can be used to create a simple GUI.
    """

    def __init__(self, name, tab_stop=True):
        """
        :param name: The name of this Widget.
        :param tab_stop: Whether this widget should take focus or not when
                         tabbing around the Frame.
        """
        super(Widget, self).__init__()
        # Internal properties
        self._name = name
        self._label = None
        self._frame = None
        self._value = None
        self._has_focus = False
        self._x = self._y = 0
        self._w = self._h = 0
        self._offset = 0

        # Public properties
        self.is_tab_stop = tab_stop

    def register_frame(self, frame):
        """
        Register the Frame that owns this Widget.
        :param frame: The owning Frame.
        """
        self._frame = frame

    def set_layout(self, x, y, offset, w, h):
        """
        Set the size and position of the Widget.

        :param x: The x position of the widget.
        :param y: The y position of the widget.
        :param offset: The allowed label size for the widget.
        :param x: The width of the widget.
        :param x: The height of the widget.
        """
        self._x = x
        self._y = y
        self._offset = offset
        self._w = w
        self._h = h

    def focus(self):
        """
        Call this to give this Widget the input focus.
        """
        self._has_focus = True
        if not self._frame.canvas.is_visible(self._x, self._y):
            if self._y < self._frame.canvas.start_line:
                self._frame.canvas.scroll_to(self._y)
            else:
                line = max(0, self._y - self._frame.canvas.height + self._h)
                self._frame.canvas.scroll_to(line)

    def blur(self):
        """
        Call this to give take the input focus from this Widget.
        """
        self._has_focus = False

    def _draw_label(self):
        """
        Draw the label for this widget if needed.
        """
        if self._label is not None:
            (colour, attr, bg) = self._frame.palette["label"]
            self._frame.canvas.paint(
                self._label, self._x, self._y, colour, attr, bg)

    @abstractmethod
    def update(self, frame_no):
        """
        The update method is called whenever this widget needs to redraw itself.

        :param frame_no: The frame number for this screen update.
        """

    @abstractmethod
    def reset(self):
        """
        The reset method is called whenever the widget needs to go back to its
        default (initially created) state.
        """

    @abstractmethod
    def process_event(self, event):
        """
        Process any input event.

        :param event: The event that was triggered.
        :returns: None if the Effect processed the event, else the original
                  event.
        """

    @property
    def label(self):
        """
        The label for this widget.  Can be `None`.
        """
        return self._label

    @property
    def value(self):
        """
        The value to return for this widget based on the user's input.
        """
        return self._value

    @abstractmethod
    def required_height(self, offset, width):
        """
        Calculate the minimum required height for this widget.

        :param offset: The allowed width for any labels.
        :param width: The total width of the widget, including labels.
        """


class Label(Widget):
    """
    A simple text label.
    """

    def __init__(self, label):
        """
        :param label: The text to be displayed for the Label.
        """
        # Labels have no value and so should have no name for look-ups either.
        super(Label, self).__init__(None, tab_stop=False)
        # Although this is a label, we don't want it to contribute to the layout
        # tab calculations, so leave internal `_label` value as None.
        self._text = label

    def process_event(self, event):
        # Labels have no user interactions
        return event

    def update(self, frame_no):
        (colour, attr, bg) = self._frame.palette["label"]
        self._frame.canvas.print_at(
            self._text, self._x, self._y + 1, colour, attr, bg)

    def reset(self):
        pass

    def required_height(self, offset, width):
        # Allow one line for text and a blank spacer before it.
        return 2


class Divider(Widget):
    """
    A simple divider to break up a group of widgets.
    """

    def __init__(self, draw_line=True, height=1):
        """
        :param draw_line: Whether to draw a line in the centre of the gap.
        :param height: The required vertical gap.
        """
        # Dividers have no value and so should have no name for look-ups either.
        super(Divider, self).__init__(None, tab_stop=False)
        self._draw_line = draw_line
        self._required_height = height

    def process_event(self, event):
        # Dividers have no user interactions
        return event

    def update(self, frame_no):
        (colour, attr, bg) = self._frame.palette["borders"]
        if self._draw_line:
            self._frame.canvas.print_at("-" * self._w,
                                        self._x,
                                        self._y + (self._required_height // 2),
                                        colour, attr, bg)

    def reset(self):
        pass

    def required_height(self, offset, width):
        # Allow one line for text and a blank spacer before it.
        return self._required_height


class Text(Widget):
    """
    A Text widget is a single line input field.  It consists of an optional
    label and an entry box.
    """

    def __init__(self, text, label=None, name=None):
        """
        :param text: The initial text to put in the widget.
        :param label: An optional label for the widget.
        :param name: The name for the widget.
        """
        super(Text, self).__init__(name)
        self._text = text
        self._label = label
        self._column = 0
        self._start_column = 0

    def update(self, frame_no):
        self._draw_label()

        # Calculate new visible limits if needed.
        width = self._w - self._offset
        self._start_column = max(0, max(self._column - width + 1,
                                        min(self._start_column, self._column)))

        # Render visible portion of the text.
        (colour, attr, bg) = self._frame.palette["edit_text"]
        self._frame.canvas.print_at(
            self._value[self._start_column:self._start_column + width],
            self._x + self._offset,
            self._y,
            colour, attr, bg)

        # Since we switch off the standard cursor, we need to emulate our own
        # if we have the input focus.
        if self._has_focus:
            (colour, attr, bg) = self._frame.palette["edit_text"]
            cursor = " "
            if frame_no % 10 < 5:
                attr |= Screen.A_REVERSE
            if self._column < len(self._value):
                cursor = self._value[self._column]
            self._frame.canvas.print_at(
                cursor,
                self._x + self._offset + self._column - self._start_column,
                self._y,
                colour, attr, bg)

    def reset(self):
        # Reset to original data and move to end of the text.
        self._value = self._text
        self._column = len(self._text)

    def process_event(self, event):
        if isinstance(event, KeyboardEvent):
            if event.key_code == Screen.KEY_BACK:
                if self._column > 0:
                    # Delete character in front of cursor.
                    self._value = "".join([
                        self._value[:self._column - 1],
                        self._value[self._column:]])
                    self._column -= 1
            elif event.key_code == Screen.KEY_LEFT:
                self._column -= 1
                self._column = max(self._column, 0)
            elif event.key_code == Screen.KEY_RIGHT:
                self._column += 1
                self._column = min(len(self._value), self._column)
            elif event.key_code == Screen.KEY_HOME:
                self._column = 0
            elif event.key_code == Screen.KEY_END:
                self._column = len(self._value)
            elif 32 <= event.key_code < 256:
                # Insert any visible text at the current cursor position.
                self._value = chr(event.key_code).join([
                    self._value[:self._column],
                    self._value[self._column:]])
                self._column += 1
            else:
                # Ignore any other key press.
                return event
        else:
            # Ignore non-keyboard events
            return event

    def required_height(self, offset, width):
        return 1


class CheckBox(Widget):
    """
    A CheckBox widget is used to ask for simple Boolean (i.e. yes/no) input.  It
    consists of an optional label (typically used for the first in a group of
    CheckBoxes), the box and a field name.
    """

    def __init__(self, text, label=None, name=None):
        """
        :param text: The text to explain this specific field to the user.
        :param label: An optional label for the widget.
        :param name: The internal name for the widget.
        """
        super(CheckBox, self).__init__(name)
        self._text = text
        self._label = label

    def update(self, frame_no):
        self._draw_label()

        # Render this checkbox.
        (colour, attr, bg) = self._frame.palette[
            "selected_field" if self._has_focus else "field"]
        self._frame.canvas.print_at(
            "[{}] {}".format("X" if self._value else " ", self._text),
            self._x + self._offset,
            self._y,
            colour, attr, bg)

    def reset(self):
        self._value = False

    def process_event(self, event):
        if isinstance(event, KeyboardEvent):
            if event.key_code in [ord(" "), 10, 13]:
                self._value = not self._value
            else:
                # Ignore any other key press.
                return event
        else:
            # Ignore non-keyboard events
            return event

    def required_height(self, offset, width):
        return 1


class RadioButtons(Widget):
    """
    A RadioButtons widget is used to ask for one of a list of values to be
    selected by the user. It consists of an optional label and then a list of
    selection bullets with field names.
    """

    def __init__(self, options, label=None, name=None):
        """
        :param options: A list of (text, value) tuples for each radio button.
        :param label: An optional label for the widget.
        :param name: The internal name for the widget.
        """
        super(RadioButtons, self).__init__(name)
        self._options = options
        self._label = label
        self._selection = 0
        self._start_column = 0

    def update(self, frame_no):
        self._draw_label()

        # Render the list of radio buttons.
        for i, (text, _) in enumerate(self._options):
            check = " "
            (colour, attr, bg) = self._frame.palette["field"]
            if i == self._selection:
                check = "X"
                if self._has_focus:
                    (colour, attr, bg) = self._frame.palette["selected_field"]
            self._frame.canvas.print_at(
                "({}) {}".format(check, text),
                self._x + self._offset,
                self._y + i,
                colour, attr, bg)

    def reset(self):
        self._selection = 0
        self._value = self._options[self._selection]

    def process_event(self, event):
        if isinstance(event, KeyboardEvent):
            if event.key_code == Screen.KEY_UP:
                self._selection = max(self._selection - 1, 0)
                self._value = self._options[self._selection]
            elif event.key_code == Screen.KEY_DOWN:
                self._selection = min(self._selection + 1,
                                      len(self._options) - 1)
                self._value = self._options[self._selection]
            else:
                # Ignore any other key press.
                return event
        else:
            # Ignore non-keyboard events
            return event

    def required_height(self, offset, width):
        return len(self._options)


class TextBox(Widget):
    """
    A TextBox is a simple widget for recording and displaying the text that has
    been typed into it (when it has the focus).  It consists of a simple
    framed box with option label.  It can take multi-line input.
    """

    def __init__(self, text, height, label=None, name=None):
        """
        :param text: The initial text to put in the TextBox.
        :param height: The required number of input lines for this TextBox.
        :param label: An optional label for the widget.
        :param name: The name for the TextBox.
        """
        super(TextBox, self).__init__(name)
        self._text = text
        self._label = label
        self._line = 0
        self._column = 0
        self._start_line = 0
        self._start_column = 0
        self._required_height = height

    def update(self, frame_no):
        self._draw_label()

        # Calculate new visible limits if needed.
        width = self._w - self._offset
        self._start_line = max(0, max(self._line - self._h + 3,
                                      min(self._start_line, self._line)))
        self._start_column = max(0, max(self._column - width + 3,
                                        min(self._start_column, self._column)))

        # Create box rendered text now.
        box = Box(width, self._h).rendered_text

        # Redraw the frame and label if needed.
        (colour, attr, bg) = self._frame.palette["borders"]
        for (i, line) in enumerate(box[0]):
            self._frame.canvas.paint(
                line, self._x, self._y + i, colour, attr, bg)

        # Render visible portion of the text.
        (colour, attr, bg) = self._frame.palette["edit_text"]
        for i, text in enumerate(self._value):
            if self._start_line <= i < self._start_line + self._h - 2:
                self._frame.canvas.print_at(
                    text[self._start_column:self._start_column + width - 2],
                    self._x + 1,
                    self._y + i + 1 - self._start_line,
                    colour, attr, bg)

        # Since we switch off the standard cursor, we need to emulate our own
        # if we have the input focus.
        if self._has_focus:
            (colour, attr, bg) = self._frame.palette["edit_text"]
            cursor = " "
            if frame_no % 10 < 5:
                attr |= Screen.A_REVERSE
            elif self._column < len(self.value[self._line]):
                cursor = self.value[self._line][self._column]
            self._frame.canvas.print_at(
                cursor,
                self._x + self._column + 1 - self._start_column,
                self._y + self._line + 1 - self._start_line,
                colour, attr, bg)

    def reset(self):
        # Reset to original data and move to end of the text.
        self._value = self._text.split("\n")
        self._line = len(self._value) - 1
        self._column = len(self._value[self._line])

    def process_event(self, event):
        if isinstance(event, KeyboardEvent):
            if event.key_code in [10, 13]:
                # Split and insert line  on CR or LF.
                self._value.insert(self._line + 1,
                                   self._value[self._line][self._column:])
                self._value[self._line] = self._value[self._line][:self._column]
                self._line += 1
                self._column = 0
            elif event.key_code == Screen.KEY_BACK:
                if self._column > 0:
                    # Delete character in front of cursor.
                    self._value[self._line] = "".join([
                        self._value[self._line][:self._column - 1],
                        self._value[self._line][self._column:]])
                    self._column -= 1
                else:
                    if self._line > 0:
                        # Join this line with previous
                        self._line -= 1
                        self._column = len(self._value[self._line])
                        self._value[self._line] += self._value.pop(self._line+1)
            elif event.key_code == Screen.KEY_UP:
                # Move up one line in text
                self._line = max(0, self._line - 1)
                if self._column >= len(self._value[self._line]):
                    self._column = len(self._value[self._line])
            elif event.key_code == Screen.KEY_DOWN:
                # Move down one line in text
                self._line = min(len(self._value) - 1, self._line + 1)
                if self._column >= len(self._value[self._line]):
                    self._column = len(self._value[self._line])
            elif event.key_code == Screen.KEY_LEFT:
                # Move left one char, wrapping to previous line if needed.
                self._column -= 1
                if self._column < 0:
                    if self._line > 0:
                        self._line -= 1
                        self._column = len(self._value[self._line])
                    else:
                        self._column = 0
            elif event.key_code == Screen.KEY_RIGHT:
                # Move right one char, wrapping to next line if needed.
                self._column += 1
                if self._column > len(self._value[self._line]):
                    if self._line < len(self._value) - 1:
                        self._line += 1
                        self._column = 0
                    else:
                        self._column = len(self._value[self._line])
            elif event.key_code == Screen.KEY_HOME:
                # Go to the start of this line
                self._column = 0
            elif event.key_code == Screen.KEY_END:
                # Go to the end of this line
                self._column = len(self._value[self._line])
            elif 32 <= event.key_code < 256:
                # Insert any visible text at the current cursor position.
                self._value[self._line] = chr(event.key_code).join([
                    self._value[self._line][:self._column],
                    self._value[self._line][self._column:]])
                self._column += 1
            else:
                # Ignore any other key press.
                return event
        else:
            # Ignore non-keyboard events
            return event

    def required_height(self, offset, width):
        # Allow for extra border lines
        return self._required_height + 2