.. _supported-esps:

Supported ESPs
==============

Anymail currently supports these Email Service Providers.
Click an ESP's name for specific Anymail settings required,
and notes about any quirks or limitations:

.. these are listed in alphabetical order

.. toctree::
   :maxdepth: 1

   amazon_ses
   brevo
   mailersend
   mailgun
   mailjet
   mandrill
   postal
   postmark
   resend
   sendgrid
   sparkpost
   unisender_go


Anymail feature support
-----------------------

The table below summarizes the Anymail features supported for each ESP.
(Scroll it to the left and right to see all ESPs.)

.. currentmodule:: anymail.message

.. It's much easier to edit esp-feature-matrix.csv with a CSV-aware editor, such as:
..   PyCharm (Pro has native CSV support; use a CSV editor plugin with Community)
..   VSCode with a CSV editor extension
..   Excel (watch out for charset issues), Apple Numbers, or Google Sheets
.. Every row must have the same number of columns. If you add a column, you must
.. also add a comma to each sub-heading row. (A CSV editor should handle this for you.)
.. Please keep columns sorted alphabetically by ESP name.

.. csv-table::
    :file: esp-feature-matrix.csv
    :header-rows: 1
    :widths: auto
    :class: sticky-left

Trying to choose an ESP? Please **don't** start with this table. It's far more
important to consider things like an ESP's deliverability stats, latency, uptime,
and support for developers. The *number* of extra features an ESP offers is almost
meaningless. (And even specific features don't matter if you don't plan to use them.)


Other ESPs
----------

Don't see your favorite ESP here? Anymail is designed to be extensible.
You can suggest that Anymail add an ESP, or even contribute
your own implementation to Anymail. See :ref:`contributing`.
